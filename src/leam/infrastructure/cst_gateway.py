"""Gateway wrapper for CST execution."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import load_config, resolve_cst_path, get_python_libs_path, _ensure_pythonpath
from ..models import SessionPaths
from ..services.optimization_goals import GoalPlan
from ..services.parameter_service import ParameterService
from ..services.simulation_validation_service import SimulationValidationService
from ..tools import CstRunner, strip_parameters_store_call


class CstGateway:
    """Facade over CstRunner with user-friendly error handling text."""

    @staticmethod
    def _setup_cst_pythonpath() -> None:
        """Read cst_path from config.json and add python_cst_libraries to sys.path."""
        config = load_config()
        cst_path = resolve_cst_path(config)
        if cst_path:
            python_libs = get_python_libs_path(cst_path)
            _ensure_pythonpath(python_libs)

    @staticmethod
    def build_history_tasks(paths: SessionPaths) -> Dict[str, str]:
        return {
            "Parameters": str(paths.parameters),
            "Materials": str(paths.materials),
            "3D Model": str(paths.model),
            "Boolean Operations": str(paths.boolean),
        }

    def run(self, history_tasks: Dict[str, str], save_path: Path) -> None:
        print("\n开始连接 CST 并创建工程 ...")
        self._setup_cst_pythonpath()
        try:
            runner = CstRunner(create_new_if_none=False)
        except ImportError:
            print(
                "\n[跳过 CST] 未找到 CST Python 库。\n"
                "请确认 CST Studio Suite 已安装，并将其 Python 库目录加入 PYTHONPATH，\n"
                "例如：\n"
                "  $env:PYTHONPATH = 'C:\\Program Files (x86)\\CST Studio Suite 2024\\AMD64\\python_cst_libraries'\n"
                "VBA / JSON 文件已正常生成，待 CST 环境就绪后可用 rerun 模式重新导入。"
            )
            return
        except RuntimeError as exc:
            print(
                f"\n[跳过 CST] 无法连接到 CST DesignEnvironment：{exc}\n"
                "请先手动启动 CST Studio Suite，然后重新运行本程序（选择 rerun 模式）。"
            )
            return

        try:
            runner.set_history_tasks(history_tasks)
            runner.create_project(str(save_path))
            print("已生成 CST 工程：", save_path)
        except Exception as exc:
            print(f"\n[CST 错误] 建模过程出现异常：{exc}")

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _manifest_base(simulation_config: Dict[str, Any], status: str) -> Dict[str, Any]:
        return {
            "status": status,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "frequency_ghz": simulation_config.get("frequency", {}),
            "solver": simulation_config.get("solver", {}),
            "export": simulation_config.get("export", {}),
        }

    def run_with_simulation(
        self,
        history_tasks: Dict[str, str],
        save_path: Path,
        simulation_config: Dict[str, Any],
        *,
        results_dir: Path,
        manifest_path: Path,
        audit_path: Optional[Path] = None,
        nl_request: str = "",
        parsed_config: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build model, run simulation, export S11, and persist result metadata.
        """
        print("\n仿真配置（将送入 CST）：")
        print(SimulationValidationService.format_summary(simulation_config))
        print("\n开始连接 CST 并执行建模+仿真 ...")
        self._setup_cst_pythonpath()
        runner = CstRunner(create_new_if_none=False)

        export_cfg = simulation_config.get("export", {}).get("s11", {})
        export_format = str(export_cfg.get("format", "touchstone")).lower()
        export_name = "s11.s1p" if export_format == "touchstone" else "s11.csv"
        export_path = results_dir / "sparams" / export_name

        if audit_path:
            self._write_json(
                audit_path,
                {
                    "natural_language": nl_request,
                    "parsed_config": parsed_config or {},
                    "validation": validation or {},
                    "effective_config": simulation_config,
                },
            )

        try:
            runner.set_history_tasks(history_tasks)
            runner.create_project(str(save_path), close_project_after_save=False)
            runner.run_simulation(simulation_config)
            export_result = runner.export_s11(str(export_path), export_format=export_format)
            if runner.prj is not None:
                runner.prj.save(str(save_path), include_results=True)

            manifest = self._manifest_base(simulation_config, status="success")
            manifest.update(
                {
                    "result_file": export_result["path"],
                    "result_format": export_result["format"],
                    "degraded_export": bool(export_result.get("degraded_export", False)),
                }
            )
            self._write_json(manifest_path, manifest)
            print("已完成仿真与导出：", export_result["path"])
            return manifest
        except Exception as exc:
            manifest = self._manifest_base(simulation_config, status="failed")
            manifest["error"] = str(exc)
            self._write_json(manifest_path, manifest)
            raise
        finally:
            runner.close_project()

    def simulate_existing_project(
        self,
        project_path: Path,
        simulation_config: Dict[str, Any],
        *,
        results_dir: Path,
        manifest_path: Path,
        audit_path: Optional[Path] = None,
        nl_request: str = "",
        parsed_config: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Open an existing CST project, run simulation, and export S11.
        """
        if not project_path.exists():
            raise FileNotFoundError(f"CST 工程不存在：{project_path}")

        print("\n仿真配置（将应用到已有 .cst 工程）：")
        print(SimulationValidationService.format_summary(simulation_config))
        print("\n开始连接 CST 并执行已有工程仿真 ...")
        self._setup_cst_pythonpath()
        runner = CstRunner(create_new_if_none=False, project_path=str(project_path))

        export_cfg = simulation_config.get("export", {}).get("s11", {})
        export_format = str(export_cfg.get("format", "touchstone")).lower()
        export_name = "s11.s1p" if export_format == "touchstone" else "s11.csv"
        export_path = results_dir / "sparams" / export_name

        if audit_path:
            self._write_json(
                audit_path,
                {
                    "natural_language": nl_request,
                    "parsed_config": parsed_config or {},
                    "validation": validation or {},
                    "effective_config": simulation_config,
                },
            )

        try:
            runner.run_simulation(simulation_config)
            export_result = runner.export_s11(str(export_path), export_format=export_format)
            if runner.prj is not None:
                runner.prj.save(str(project_path), include_results=True)

            manifest = self._manifest_base(simulation_config, status="success")
            manifest.update(
                {
                    "result_file": export_result["path"],
                    "result_format": export_result["format"],
                    "degraded_export": bool(export_result.get("degraded_export", False)),
                    "source_project": str(project_path),
                }
            )
            self._write_json(manifest_path, manifest)
            print("已完成仿真与导出：", export_result["path"])
            return manifest
        except Exception as exc:
            manifest = self._manifest_base(simulation_config, status="failed")
            manifest["error"] = str(exc)
            manifest["source_project"] = str(project_path)
            self._write_json(manifest_path, manifest)
            raise
        finally:
            runner.close_project()

    # ------------------------------------------------------------------
    # CST Optimizer1D flow
    # ------------------------------------------------------------------

    def run_optimization(
        self,
        *,
        paths: SessionPaths,
        variables: List[Dict[str, Any]],
        goals: List[GoalPlan],
        algorithm: str = "Trust Region Framework",
        max_evaluations: int = 40,
        use_current_as_init: bool = True,
        nl_request: str = "",
        parsed_request: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run CST's Optimizer1D on an existing ``.cst`` project.

        Follows the ParameterList / History separation principle:

        1. Python seeds ``ParameterList`` directly with the initial
           values from ``<output>_parameters.bas`` *and* any explicit
           ``init`` supplied in ``variables``.
        2. The geometry-referencing VBAs (parameters/materials/model/
           boolean) are re-applied to history with the final
           ``StoreParameters names, values`` call stripped, so the
           optimizer's trial values never get overwritten.
        3. Optimizer1D is configured with the variables, goals, and
           algorithm, then started synchronously.
        4. Best-so-far parameter values are read back via the Python
           API and persisted alongside an optimization manifest.

        Returns the manifest dict that was written to disk.
        """
        project_path = paths.cst
        if not project_path.exists():
            raise FileNotFoundError(
                f"CST project not found for optimization: {project_path}"
            )

        opt_dir = paths.optimization_dir
        opt_dir.mkdir(parents=True, exist_ok=True)

        initial_params = ParameterService.parse_bas(
            paths.parameters.read_text(encoding="utf-8")
        )
        seeds: Dict[str, str] = {p["name"]: p["value"] for p in initial_params}

        audit_payload = {
            "natural_language": nl_request,
            "parsed_request": parsed_request or {},
            "variables": variables,
            "goals": [g.to_dict() for g in goals],
            "algorithm": algorithm,
            "max_evaluations": max_evaluations,
            "use_current_as_init": use_current_as_init,
            "initial_parameters": seeds,
        }
        self._write_json(paths.optimization_audit, audit_payload)

        print("\n开始连接 CST 并执行 Optimizer1D ...")
        self._setup_cst_pythonpath()
        runner = CstRunner(create_new_if_none=False, project_path=str(project_path))

        stripped_parameters_path = opt_dir / "parameters_optimizer_safe.bas"
        stripped_parameters_path.write_text(
            strip_parameters_store_call(paths.parameters.read_text(encoding="utf-8")),
            encoding="utf-8",
        )

        manifest = self._manifest_base(
            simulation_config={}, status="running"
        )
        manifest.update(
            {
                "mode": "optimizer",
                "algorithm": algorithm,
                "max_evaluations": max_evaluations,
                "source_project": str(project_path),
                "variables": variables,
                "goals": [g.to_dict() for g in goals],
            }
        )

        try:
            runner.store_parameters(seeds)
            for var in variables:
                if var.get("init") is not None:
                    runner.store_parameter(var["name"], var["init"])

            runner.add_to_history("Parameters (optimizer-safe)", str(stripped_parameters_path))
            if paths.materials.exists():
                runner.add_to_history("Materials", str(paths.materials))
            if paths.model.exists():
                runner.add_to_history("3D Model", str(paths.model))
            if paths.boolean.exists():
                runner.add_to_history("Boolean Operations", str(paths.boolean))

            runner.configure_optimizer(
                variables=variables,
                goals_vba=[g.vba_snippet for g in goals],
                algorithm=algorithm,
                max_evaluations=max_evaluations,
                use_current_as_init=use_current_as_init,
            )
            runner.run_optimizer()

            best_params: Dict[str, str] = {}
            for var in variables:
                name = var["name"]
                value = runner.get_parameter(name)
                if value is not None:
                    best_params[name] = value

            if runner.prj is not None:
                runner.prj.save(str(project_path), include_results=True)

            self._write_json(
                paths.best_parameters,
                {
                    "parameters": best_params,
                    "seeds": seeds,
                    "variables": variables,
                    "algorithm": algorithm,
                },
            )

            manifest.update({"status": "success", "best_parameters": best_params})
            self._write_json(paths.optimization_manifest, manifest)
            print(
                f"已完成优化: 共 {len(variables)} 个参数，{len(goals)} 个 goal "
                f"(algorithm={algorithm})."
            )
            return manifest
        except Exception as exc:
            manifest.update({"status": "failed", "error": str(exc)})
            self._write_json(paths.optimization_manifest, manifest)
            raise
        finally:
            runner.close_project()

