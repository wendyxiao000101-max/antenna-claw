"""Template-based workflow orchestration.

When a user description matches a registered antenna template, this
workflow runs the deterministic template pipeline instead of the
LLM-based generation chain.
"""

from pathlib import Path
from typing import Any, Dict, Tuple

from ..infrastructure import CstGateway, OutputRepository
from ..templates import TemplateRunner
from .contracts import WORKFLOW_EXECUTION_MODES


_ALLOWED_EXECUTION_MODES = WORKFLOW_EXECUTION_MODES["template"]


class TemplateWorkflow:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.output_repo = OutputRepository(project_root)
        self.cst_gateway = CstGateway()
        from ..services import SimulationConfigService, SimulationValidationService

        self.simulation_config_service = SimulationConfigService()
        self.simulation_validation_service = SimulationValidationService()
        self.runner = TemplateRunner()

    def run(
        self,
        description: str,
        output_name: str,
        *,
        run_cst: bool = True,
        execution_mode: str = "build_only",
        simulation_request: str = "",
        skip_review: bool = True,
    ) -> Dict[str, Any]:
        self._validate_execution_mode(execution_mode)
        result = self.runner.match(description)
        if result is None:
            print("\n未匹配到任何已注册模板。")
            return {"matched": False, "template_id": None, "files": []}

        template, match_result = result
        print(f"\n匹配到模板: {template.metadata.name} (v{template.metadata.version})")

        paths = self.output_repo.build_paths(output_name)
        existing = self.output_repo.existing_outputs(paths)
        if existing:
            print("\n警告：以下同名输出已存在，新的运行可能会覆盖它们：")
            for p in existing:
                print(" -", p)

        files = self.runner.run(
            template=template,
            match_result=match_result,
            output_dir=paths.output_dir,
            output_name=output_name,
            skip_review=skip_review,
        )

        print("\n已生成文件：")
        for f in files:
            print(f"  - {f.name}")

        if execution_mode == "build_only":
            if run_cst:
                self._run_cst(paths, files)
            else:
                print("\n本次未执行 CST，仅生成 .json / .bas 文件。")
            return {
                "matched": True,
                "template_id": template.metadata.template_id,
                "files": [str(f) for f in files],
            }

        raw_cfg, validation = self._prepare_simulation_config(simulation_request)
        if not validation["is_valid"]:
            self._raise_validation_error(validation["errors"])
        if validation["warnings"]:
            print("\n仿真配置告警：")
            for warning in validation["warnings"]:
                print(" -", warning)

        if execution_mode == "simulate_and_export":
            self._run_cst_with_simulation(paths, files, simulation_request, raw_cfg, validation)
            return {
                "matched": True,
                "template_id": template.metadata.template_id,
                "files": [str(f) for f in files],
            }

        raise RuntimeError(f"未知执行模式: {execution_mode}")

    def simulate_existing(
        self,
        output_name: str,
        simulation_request: str,
    ) -> Dict[str, Any]:
        """Re-simulate on the existing .cst project without rebuilding geometry.

        Intended for headless reuse: after a successful
        ``simulate_and_export`` round, subsequent rounds (e.g. OpenClaw
        tweaking simulation config after optimization) can just reopen
        the saved project without re-running the build.
        """
        paths = self.output_repo.build_paths(output_name)
        if not paths.cst.exists():
            raise FileNotFoundError(
                f"CST 工程不存在：{paths.cst}（请先执行一次 build+simulate）"
            )

        raw_cfg, validation = self._prepare_simulation_config(simulation_request)
        if not validation["is_valid"]:
            self._raise_validation_error(validation["errors"])
        if validation["warnings"]:
            print("\n仿真配置告警：")
            for warning in validation["warnings"]:
                print(" -", warning)

        self.cst_gateway.simulate_existing_project(
            project_path=paths.cst,
            simulation_config=validation["config"],
            results_dir=paths.results_dir,
            manifest_path=paths.manifest,
            audit_path=paths.simulation_audit,
            nl_request=simulation_request,
            parsed_config=raw_cfg,
            validation=validation,
        )
        return {"matched": True, "output_name": output_name}

    def _run_cst(self, paths, files) -> None:
        file_map = {f.name: str(f) for f in files}

        def _find(suffix: str) -> str:
            for name, path in file_map.items():
                if name.endswith(suffix):
                    return path
            return ""

        history_tasks = {
            "Parameters": _find("_parameters.bas"),
            "Materials": _find("_materials.bas"),
            "3D Model": _find("_model.bas"),
            "Boolean Operations": _find("_boolean.bas"),
        }
        history_tasks = {k: v for k, v in history_tasks.items() if v}
        self.cst_gateway.run(history_tasks, paths.cst)

    def _run_cst_with_simulation(
        self,
        paths,
        files,
        simulation_request: str,
        raw_cfg: Dict[str, Any],
        validation: Dict[str, Any],
    ) -> None:
        file_map = {f.name: str(f) for f in files}

        def _find(suffix: str) -> str:
            for name, path in file_map.items():
                if name.endswith(suffix):
                    return path
            return ""

        history_tasks = {
            "Parameters": _find("_parameters.bas"),
            "Materials": _find("_materials.bas"),
            "3D Model": _find("_model.bas"),
            "Boolean Operations": _find("_boolean.bas"),
        }
        history_tasks = {k: v for k, v in history_tasks.items() if v}
        self.cst_gateway.run_with_simulation(
            history_tasks=history_tasks,
            save_path=paths.cst,
            simulation_config=validation["config"],
            results_dir=paths.results_dir,
            manifest_path=paths.manifest,
            audit_path=paths.simulation_audit,
            nl_request=simulation_request,
            parsed_config=raw_cfg,
            validation=validation,
        )

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
            f"template 工作流仅支持以下执行模式: {allowed}；收到: {execution_mode}"
        )

    def list_available(self) -> None:
        templates = self.runner.list_templates()
        if not templates:
            print("  （暂无已注册模板）")
            return
        print(f"\n已注册模板（共 {len(templates)} 个）：")
        for meta in templates:
            print(f"  [{meta.template_id}] {meta.name} — {meta.antenna_type}, {meta.substrate}")
