"""Rerun workflow orchestration using existing generated files."""

from pathlib import Path
from typing import Any, Dict, Tuple

from ..infrastructure import CstGateway, OutputRepository
from ..models import DesignSession
from ..services import (
    SimulationConfigService,
    SimulationValidationService,
    ValidationService,
)
from .contracts import WORKFLOW_EXECUTION_MODES


_ALLOWED_EXECUTION_MODES = WORKFLOW_EXECUTION_MODES["rerun"]


class RerunWorkflow:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.output_repo = OutputRepository(project_root)
        self.validation_service = ValidationService()
        self.simulation_config_service = SimulationConfigService()
        self.simulation_validation_service = SimulationValidationService()
        self.cst_gateway = CstGateway()

    def run(
        self,
        base_name: str,
        *,
        run_cst: bool = True,
        execution_mode: str = "build_only",
        simulation_request: str = "",
    ) -> None:
        self._validate_execution_mode(execution_mode)
        paths = self.output_repo.build_paths(base_name)
        session = DesignSession(
            output_name=base_name,
            mode="strong",
            description="",
            paths=paths,
        )
        missing = self.output_repo.missing_required_for_rerun(paths)
        if missing:
            print("\n缺少以下文件，无法重放：")
            for path in missing:
                print(" -", path)
            raise RuntimeError("现有输出文件不完整，无法生成 CST。")

        print("\n将重放以下文件：")
        for path in session.paths.required_rerun_files:
            print(" -", path)

        errors = self.validation_service.run_consistency(session)
        if errors:
            print("\n检测到一致性问题：")
            for err in errors:
                print(" -", err)
            raise RuntimeError("现有输出未通过一致性校验，已停止送入 CST。")

        if execution_mode == "build_only":
            if run_cst:
                tasks = self.cst_gateway.build_history_tasks(session.paths)
                self.cst_gateway.run(tasks, session.paths.cst)
            else:
                print("\n本次未执行 CST，已列出可用文件。")
            return

        raw_cfg, validation = self._prepare_simulation_config(simulation_request)
        if not validation["is_valid"]:
            self._raise_validation_error(validation["errors"])
        if validation["warnings"]:
            print("\n仿真配置告警：")
            for warning in validation["warnings"]:
                print(" -", warning)

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

    @staticmethod
    def _validate_execution_mode(execution_mode: str) -> None:
        if execution_mode in _ALLOWED_EXECUTION_MODES:
            return
        allowed = ", ".join(_ALLOWED_EXECUTION_MODES)
        raise RuntimeError(
            f"rerun 工作流仅支持以下执行模式: {allowed}；收到: {execution_mode}"
        )

