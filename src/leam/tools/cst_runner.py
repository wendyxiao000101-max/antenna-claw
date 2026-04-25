import os
import re
from contextlib import nullcontext
from typing import Any, Dict, List, Optional


class CstRunner:
    """Run generated VBA macros in CST Studio Suite."""

    def __init__(
        self,
        create_new_if_none: bool = False,
        project_path: Optional[str] = None,
        use_active_project: bool = False,
    ):
        """
        Connect to an existing CST DesignEnvironment or create one.

        ``cst.interface`` is imported here (lazily) so that the rest of the
        package can be imported on machines where CST Studio Suite is not
        installed — the ImportError is only raised when you actually try to
        connect to CST.
        """
        try:
            import cst.interface as _cst_iface
        except ImportError as exc:
            raise ImportError(
                "The 'cst' Python package was not found. "
                "Make sure CST Studio Suite is installed and its Python "
                "libraries directory is added to PYTHONPATH (or sys.path)."
            ) from exc

        pids = _cst_iface.running_design_environments()

        if pids:
            self.de = _cst_iface.DesignEnvironment.connect(pids[0])
        elif create_new_if_none:
            self.de = _cst_iface.DesignEnvironment.connect_to_any_or_new()
        else:
            raise RuntimeError(
                "No running CST DesignEnvironment found. "
                "Please start CST Studio Suite manually first."
            )

        self.prj = None
        if project_path:
            normalized = os.path.abspath(project_path)
            if not os.path.exists(normalized):
                raise FileNotFoundError(f"CST project not found: {normalized}")
            try:
                self.prj = self.de.get_open_project(normalized)
            except Exception:
                self.prj = self.de.open_project(normalized)
        elif use_active_project and self.de.has_active_project():
            self.prj = self.de.active_project()
        else:
            self.prj = self.de.new_mws()

        self.history_tasks: Dict[str, str] = {}
        self.parameter_tasks: Dict[str, str] = {}

    def _quiet_context(self):
        """Use quiet mode when supported by this CST version."""
        if hasattr(self.de, "quiet_mode_enabled"):
            return self.de.quiet_mode_enabled()
        return nullcontext()

    def set_history_tasks(self, tasks: Dict[str, str]) -> None:
        """Register VBA tasks to run via AddToHistory."""
        self.history_tasks = tasks

    def set_parameter_tasks(self, tasks: Dict[str, str]) -> None:
        """Register VBA tasks to run via Schematic.execute_vba_code."""
        self.parameter_tasks = tasks

    def _read_vba_file(self, file_path: str) -> str:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"VBA file not found: {file_path}")
        with open(file_path, "r", encoding="utf8") as vba_file:
            return vba_file.read()

    def _ensure_sub_main(self, vba_code: str) -> str:
        if re.search(
            r"^\s*(Sub|Function)\b",
            vba_code,
            flags=re.IGNORECASE | re.MULTILINE,
        ):
            return vba_code
        stripped = vba_code.strip()
        if not stripped:
            return "Sub Main()\nEnd Sub\n"
        return f"Sub Main()\n{stripped}\nEnd Sub\n"

    def add_to_history(self, description: str, file_path: str) -> None:
        """Add a VBA macro to the model history and execute it."""
        vba_code = self._read_vba_file(file_path)
        self.prj.modeler.add_to_history(description, vba_code)

    def add_history_code(self, description: str, vba_code: str) -> None:
        """Add an inline VBA snippet to model history.

        The CST modeler.add_to_history already executes the code inside its
        own Sub wrapper, so the snippet must NOT be wrapped in Sub Main().
        """
        self.prj.modeler.add_to_history(description, vba_code)

    def execute_vba_code(self, file_path: str) -> None:
        """Execute a VBA snippet via Schematic.execute_vba_code."""
        if self.prj.schematic is None:
            raise RuntimeError(
                "Schematic interface is not available for this project."
            )
        vba_code = self._read_vba_file(file_path)
        self.prj.schematic.execute_vba_code(self._ensure_sub_main(vba_code))

    def run_history_tasks(self) -> None:
        """Execute all history tasks using AddToHistory."""
        for task, vba_file in self.history_tasks.items():
            self.add_to_history(task, vba_file)

    def run_parameter_tasks(self) -> None:
        """Execute all parameter tasks using execute_vba_code."""
        if not self.parameter_tasks:
            return
        if self.prj.schematic is None:
            raise RuntimeError(
                "Schematic interface is not available for this project."
            )
        for _, vba_file in self.parameter_tasks.items():
            self.execute_vba_code(vba_file)

    def create_project(
        self,
        save_path: str,
        include_results: bool = False,
        allow_overwrite: bool = True,
        close_project_after_save: bool = True,
    ) -> None:
        """Run history tasks, save the project, and optionally close."""
        if os.path.exists(save_path) and not allow_overwrite:
            raise FileExistsError(f"File already exists: {save_path}")

        with self._quiet_context():
            self.run_history_tasks()
            self.prj.save(
                save_path,
                include_results=include_results,
            )

        if close_project_after_save:
            self.close_project()

    def apply_parameter_updates(
        self,
        save_path: Optional[str] = None,
        include_results: bool = False,
        allow_overwrite: bool = True,
        close_project_after_save: bool = True,
    ) -> None:
        """Execute parameter updates and optionally save the project."""
        if save_path and os.path.exists(save_path) and not allow_overwrite:
            raise FileExistsError(f"File already exists: {save_path}")

        with self._quiet_context():
            self.run_parameter_tasks()
            if save_path:
                self.prj.save(
                    save_path,
                    include_results=include_results,
                )

        if close_project_after_save:
            self.close_project()

    def close_project(self) -> None:
        """Close the current CST project (keep CST open)."""
        if self.prj is not None:
            self.prj.close()
            self.prj = None

    @staticmethod
    def _vba_quote(value: str) -> str:
        return str(value).replace('"', '""')

    # Mapping from human-readable boundary names (as produced by the
    # validation layer / LLM config) to the exact string tokens that
    # CST VBA ``Boundary.Xmin`` etc. accept. Keys are lowercased for
    # robust lookup; unrecognized values fall through unchanged and
    # CST will surface its own "Invalid boundary type" error.
    _BOUNDARY_VBA_TOKENS: Dict[str, str] = {
        "open add space": "expanded open",
        "open": "open",
        "pec": "electric",
        "electric": "electric",
        "pmc": "magnetic",
        "magnetic": "magnetic",
        "normal": "normal",
        "tangential": "tangential",
        "periodic": "periodic",
        "open if open": "open if open",
        "symmetry": "symmetry",
    }

    @classmethod
    def _boundary_token(cls, value: Any) -> str:
        raw = str(value).strip().lower()
        return cls._BOUNDARY_VBA_TOKENS.get(raw, raw)

    def apply_simulation_config(self, simulation_config: Dict[str, Any]) -> None:
        """
        Apply validated simulation settings to the current project.

        Notes:
        - Frequency is expected in GHz after normalization.
        - Boundary values are mapped to lowercase tokens CST macros usually accept.
        """
        freq = simulation_config.get("frequency", {})
        boundary = simulation_config.get("boundary", {})

        start = freq.get("start")
        stop = freq.get("stop")
        if start is not None and stop is not None:
            freq_code = (
                "With Solver\n"
                f' .FrequencyRange "{self._vba_quote(start)}", "{self._vba_quote(stop)}"\n'
                "End With\n"
            )
            self.add_history_code("Simulation Frequency Range", freq_code)

        if boundary:
            bmap = {
                "xmin": self._boundary_token(boundary.get("xmin", "Open Add Space")),
                "xmax": self._boundary_token(boundary.get("xmax", "Open Add Space")),
                "ymin": self._boundary_token(boundary.get("ymin", "Open Add Space")),
                "ymax": self._boundary_token(boundary.get("ymax", "Open Add Space")),
                "zmin": self._boundary_token(boundary.get("zmin", "Open Add Space")),
                "zmax": self._boundary_token(boundary.get("zmax", "Open Add Space")),
            }
            boundary_code = (
                "With Boundary\n"
                f' .Xmin "{self._vba_quote(bmap["xmin"])}"\n'
                f' .Xmax "{self._vba_quote(bmap["xmax"])}"\n'
                f' .Ymin "{self._vba_quote(bmap["ymin"])}"\n'
                f' .Ymax "{self._vba_quote(bmap["ymax"])}"\n'
                f' .Zmin "{self._vba_quote(bmap["zmin"])}"\n'
                f' .Zmax "{self._vba_quote(bmap["zmax"])}"\n'
                "End With\n"
            )
            self.add_history_code("Simulation Boundary Conditions", boundary_code)

    def run_simulation(self, simulation_config: Optional[Dict[str, Any]] = None) -> None:
        """
        Apply simulation settings (if any) and start the solver.

        Notes:
        - ``Solver.Start`` cannot be added to the history tree; CST raises
          "solver start command cannot be used inside a structure macro".
        - Solver must therefore be launched via the CST Python API
          *after* any history modifications have been applied.
        """
        with self._quiet_context():
            if simulation_config:
                self.apply_simulation_config(simulation_config)

        attempts = []
        candidates = [
            ("prj.modeler.run_solver()",
             lambda: self.prj.modeler.run_solver()),
            ("prj.run_solver()",
             lambda: self.prj.run_solver()),
            ("prj.modeler.start_solver()",
             lambda: self.prj.modeler.start_solver()),
            ("prj.start_solver()",
             lambda: self.prj.start_solver()),
        ]
        for label, caller in candidates:
            try:
                caller()
                return
            except AttributeError as exc:
                attempts.append(f"{label} -> AttributeError: {exc}")
                continue
            # For non-AttributeError exceptions the method exists but the
            # solver itself failed; re-raise so the real cause surfaces.

        raise RuntimeError(
            "无法通过 CST Python API 启动求解器。请确认安装的 CST Python 库版本支持 "
            "`prj.modeler.run_solver()` 或等价接口。已尝试: "
            + "; ".join(attempts)
        )

    def export_s11(self, output_file: str, export_format: str = "touchstone") -> Dict[str, Any]:
        """
        Export S11 result to output_file.

        Returns:
            {"path": "...", "format": "touchstone|csv", "degraded_export": bool}
        """
        export_format = (export_format or "touchstone").strip().lower()
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

        if export_format == "touchstone":
            try:
                self._export_s11_touchstone(output_file)
                return {
                    "path": output_file,
                    "format": "touchstone",
                    "degraded_export": False,
                }
            except Exception:
                # Fallback to CSV export when touchstone macro is unsupported.
                csv_path = os.path.splitext(output_file)[0] + ".csv"
                self._export_s11_csv(csv_path)
                return {
                    "path": csv_path,
                    "format": "csv",
                    "degraded_export": True,
                }

        self._export_s11_csv(output_file)
        return {
            "path": output_file,
            "format": "csv",
            "degraded_export": False,
        }

    def _export_s11_touchstone(self, output_file: str) -> None:
        quoted = self._vba_quote(os.path.abspath(output_file))
        touchstone_code = (
            "With TOUCHSTONE\n"
            " .Reset\n"
            f' .FileName "{quoted}"\n'
            " .Impedance 50\n"
            ' .FrequencyRange "Full"\n'
            " .Renormalize True\n"
            " .UseARResults False\n"
            " .SetNSamples 1001\n"
            " .Write\n"
            "End With\n"
        )
        self.add_history_code("Export S11 Touchstone", touchstone_code)

    def _export_s11_csv(self, output_file: str) -> None:
        quoted = self._vba_quote(os.path.abspath(output_file))
        csv_code = (
            'SelectTreeItem("1D Results\\S-Parameters\\S1,1")\n'
            "With ASCIIExport\n"
            " .Reset\n"
            f' .FileName "{quoted}"\n'
            " .Execute\n"
            "End With\n"
        )
        self.add_history_code("Export S11 CSV", csv_code)

    # ---------------------------------------------------------------------
    # Optimizer helpers (CST Parameter Sweep / Optimizer1D)
    # ---------------------------------------------------------------------
    #
    # Principle enforced by these helpers:
    #
    #   Python directly initializes ParameterList in CST; geometry history
    #   macros must only *reference* parameter names, not assign values.
    #
    # This avoids the optimizer's trial values being overwritten on every
    # history rebuild. The caller is expected to hand us a parameters VBA
    # that has already been "stripped" of any ``StoreParameters names,
    # values`` final call (see :func:`strip_parameters_store_call`
    # below).

    def store_parameter(self, name: str, value) -> None:
        """Directly set a single parameter on CST's ParameterList.

        Uses the Python API first; falls back to an inline VBA call so
        the method works across CST releases that expose slightly
        different Python wrappers.
        """
        if self.prj is None:
            raise RuntimeError("No open CST project; cannot set parameter.")

        value_str = str(value)
        try:
            if hasattr(self.prj, "store_parameter"):
                self.prj.store_parameter(name, value_str)
                return
        except Exception:  # noqa: BLE001 — fallback path is authoritative
            pass

        snippet = (
            f'StoreParameter "{self._vba_quote(name)}", '
            f'"{self._vba_quote(value_str)}"\n'
        )
        self.add_history_code(f"Seed parameter {name}", snippet)

    def store_parameters(self, parameters: Dict[str, Any]) -> None:
        """Bulk-seed the ParameterList from ``{name: value}`` mapping."""
        for name, value in parameters.items():
            self.store_parameter(name, value)

    def get_parameter(self, name: str) -> Optional[str]:
        """Return the current ParameterList value for ``name`` or ``None``."""
        if self.prj is None:
            return None
        for attr in ("get_parameter", "get_parameter_value"):
            fn = getattr(self.prj, attr, None)
            if fn is None:
                continue
            try:
                value = fn(name)
            except Exception:  # noqa: BLE001
                continue
            if value is not None:
                return str(value)
        return None

    def configure_optimizer(
        self,
        *,
        variables: List[Dict[str, Any]],
        goals_vba: List[str],
        algorithm: str = "Trust Region Framework",
        max_evaluations: int = 40,
        use_current_as_init: bool = True,
    ) -> None:
        """Emit the VBA that configures Optimizer1D for this run.

        ``variables`` is a list of dicts like
        ``{"name": "L", "min": 10.0, "max": 20.0, "init": 15.0}``.
        The ``init`` value is optional; when omitted CST uses whatever
        value is already in ParameterList.
        """
        if self.prj is None:
            raise RuntimeError("No open CST project; cannot configure optimizer.")

        lines: List[str] = [
            "With Optimizer1D",
            " .ResetOptimizer",
            f' .SetAlgorithm "{self._vba_quote(algorithm)}"',
            f' .SetMaxNumberOfEvaluations "{int(max_evaluations)}"',
            f' .SetUseCurrentValuesAsInit "{str(bool(use_current_as_init)).lower()}"',
            "End With",
            "",
        ]
        for var in variables:
            name = self._vba_quote(str(var["name"]))
            vmin = self._vba_quote(str(var["min"]))
            vmax = self._vba_quote(str(var["max"]))
            lines.extend(
                [
                    "With Optimizer1D",
                    f' .SelectParameter "{name}", True',
                    f' .SetParameterRange "{name}", "{vmin}", "{vmax}"',
                ]
            )
            if "init" in var and var["init"] is not None:
                init = self._vba_quote(str(var["init"]))
                lines.append(f' .SetParameterInit "{name}", "{init}"')
            lines.append("End With")
            lines.append("")

        vba = "\n".join(lines)
        self.add_history_code("Configure Optimizer1D", vba)
        for goal_snippet in goals_vba:
            self.add_history_code("Optimizer1D goal", goal_snippet)

    def run_optimizer(self) -> None:
        """Start CST's Optimizer1D synchronously.

        CST blocks the call until the optimization run completes (same
        behaviour as ``Solver.Start``). The method does not return
        best-so-far values; use :meth:`get_parameter` after the call.
        """
        if self.prj is None:
            raise RuntimeError("No open CST project; cannot run optimizer.")
        start_snippet = "With Optimizer1D\n .Start\nEnd With\n"
        self.add_history_code("Run Optimizer1D", start_snippet)