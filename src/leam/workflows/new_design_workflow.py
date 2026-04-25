"""New-design workflow orchestration (non-interactive execution only)."""

from pathlib import Path
from typing import Any, Dict, Tuple

from ..infrastructure import CstGateway, OutputRepository
from ..models import DesignSession
from ..services import (
    GenerationService,
    SimulationConfigService,
    SimulationValidationService,
    ValidationService,
)
from .contracts import WORKFLOW_EXECUTION_MODES
from .topology_revision_workflow import TopologyRevisionWorkflow


_ALLOWED_EXECUTION_MODES = WORKFLOW_EXECUTION_MODES["new"]


class NewDesignWorkflow:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.output_repo = OutputRepository(project_root)
        self.cst_gateway = CstGateway()
        self.generation_service = GenerationService()
        self.validation_service = ValidationService()
        self.simulation_config_service = SimulationConfigService()
        self.simulation_validation_service = SimulationValidationService()
        self.topology_workflow = TopologyRevisionWorkflow(self.validation_service)

    def build_session(
        self,
        description: str,
        mode: str,
        output_name: str,
    ) -> DesignSession:
        paths = self.output_repo.build_paths(output_name)
        return DesignSession(
            output_name=output_name,
            mode=mode,
            description=description,
            paths=paths,
        )

    def warn_if_existing_outputs(self, session: DesignSession) -> None:
        existing = self.output_repo.existing_outputs(session.paths)
        if not existing:
            return
        print("\n警告：以下同名输出已存在，新的运行可能会覆盖它们：")
        for path in existing:
            print(" -", path)

    def run(
        self,
        session: DesignSession,
        *,
        run_cst: bool,
        execution_mode: str = "build_only",
        simulation_request: str = "",
        enable_topology_check: bool = True,
    ) -> None:
        """Execute the new-design pipeline headlessly.

        All previously interactive prompts (design-intent confirmation,
        parameter review, geometry Q&A, topology-fix confirmation) are
        removed. Callers pass ``run_cst`` explicitly; topology auto-fix
        is opt-in via ``enable_topology_check``.
        """
        self._validate_execution_mode(execution_mode)
        if execution_mode == "simulate_only":
            self._run_with_mode(session, execution_mode, simulation_request)
            return

        self.warn_if_existing_outputs(session)
        print("\n[1/5] 生成 solids JSON ...")
        self.generation_service.generate_solids(session)
        print("[2/5] 生成参数 VBA ...")
        self.generation_service.generate_parameters(session)
        print("[3/5] 生成尺寸 JSON ...")
        self.generation_service.generate_dimensions(session)
        print("[4/5] 生成材料 VBA ...")
        self.generation_service.generate_materials(session)
        print("[5/5] 生成 3D 模型 VBA ...")
        self.generation_service.generate_model_and_boolean(session)
        if enable_topology_check:
            self.topology_workflow.run(session, self.generation_service.generate_model_and_boolean)
        self._run_consistency_or_raise(session)
        self._print_generated_files(session)
        if execution_mode == "build_only":
            if run_cst:
                self._run_cst(session)
            else:
                print("\n本次未执行 CST，仅生成 .json / .bas 文件。")
            return
        self._run_with_mode(session, execution_mode, simulation_request)

    def _run_consistency_or_raise(self, session: DesignSession) -> None:
        errors = self.validation_service.run_consistency(session)
        if errors:
            print("\n检测到一致性问题：")
            for err in errors:
                print(" -", err)
            raise RuntimeError("生成结果未通过一致性校验，已停止送入 CST。")

    @staticmethod
    def _print_generated_files(session: DesignSession) -> None:
        print("\n已生成文件：")
        for path in [
            session.paths.json,
            session.paths.parameters,
            session.paths.dimensions,
            session.paths.materials,
            session.paths.model,
            session.paths.boolean,
        ]:
            print(" -", path)

    @staticmethod
    def _validate_execution_mode(execution_mode: str) -> None:
        if execution_mode in _ALLOWED_EXECUTION_MODES:
            return
        allowed = ", ".join(_ALLOWED_EXECUTION_MODES)
        raise RuntimeError(
            f"new 工作流仅支持以下执行模式: {allowed}；收到: {execution_mode}"
        )

    def _run_cst(self, session: DesignSession) -> None:
        tasks = self.cst_gateway.build_history_tasks(session.paths)
        self.cst_gateway.run(tasks, session.paths.cst)

    def _run_with_mode(
        self,
        session: DesignSession,
        execution_mode: str,
        simulation_request: str,
    ) -> None:
        raw_cfg, validation = self._prepare_simulation_config(simulation_request)
        if not validation["is_valid"]:
            self._raise_validation_error(validation["errors"])

        if validation["warnings"]:
            print("\n仿真配置告警：")
            for warning in validation["warnings"]:
                print(" -", warning)

        if execution_mode == "simulate_and_export":
            tasks = self.cst_gateway.build_history_tasks(session.paths)
            self.cst_gateway.run_with_simulation(
                tasks,
                session.paths.cst,
                validation["config"],
                results_dir=session.paths.results_dir,
                manifest_path=session.paths.manifest,
                audit_path=session.paths.simulation_audit,
                nl_request=simulation_request,
                parsed_config=raw_cfg,
                validation=validation,
            )
            return

        if execution_mode == "simulate_only":
            self.cst_gateway.simulate_existing_project(
                session.paths.cst,
                validation["config"],
                results_dir=session.paths.results_dir,
                manifest_path=session.paths.manifest,
                audit_path=session.paths.simulation_audit,
                nl_request=simulation_request,
                parsed_config=raw_cfg,
                validation=validation,
            )
            return

        raise RuntimeError(f"未知执行模式: {execution_mode}")

    def _prepare_simulation_config(
        self,
        simulation_request: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        raw_cfg = self.simulation_config_service.parse(simulation_request)
        validation = self.simulation_validation_service.validate(raw_cfg)
        return raw_cfg, validation

    @staticmethod
    def _raise_validation_error(errors: Any) -> None:
        if not errors:
            raise RuntimeError("仿真配置无效。")
        details = []
        for err in errors:
            if not isinstance(err, dict):
                details.append(str(err))
                continue
            code = err.get("code", "UNKNOWN")
            message = err.get("message", "")
            suggestion = err.get("suggestion", "")
            details.append(f"[{code}] {message} 建议: {suggestion}".strip())
        raise RuntimeError("仿真配置校验失败：\n - " + "\n - ".join(details))
