import os
import re
import tempfile
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

        self.prj = None
        if project_path:
            normalized = os.path.abspath(project_path)
            if not os.path.exists(normalized):
                raise FileNotFoundError(f"CST project not found: {normalized}")
            self.de, self.prj = self._connect_project_environment(
                _cst_iface,
                normalized,
                create_new_if_none=create_new_if_none,
            )
        else:
            self.de = self._connect_any_environment(
                _cst_iface,
                create_new_if_none=create_new_if_none,
            )

        if self.prj is None and use_active_project and self.de.has_active_project():
            self.prj = self.de.active_project()
        elif self.prj is None:
            self.prj = self.de.new_mws()

        self.history_tasks: Dict[str, str] = {}
        self.parameter_tasks: Dict[str, str] = {}

    @staticmethod
    def _connect_any_environment(cst_iface, *, create_new_if_none: bool):
        pids = cst_iface.running_design_environments()
        if pids:
            return cst_iface.DesignEnvironment.connect(pids[0])
        if create_new_if_none:
            return cst_iface.DesignEnvironment.connect_to_any_or_new()
        raise RuntimeError(
            "No running CST DesignEnvironment found. "
            "Please start CST Studio Suite manually first."
        )

    @classmethod
    def _connect_project_environment(
        cls,
        cst_iface,
        project_path: str,
        *,
        create_new_if_none: bool,
    ):
        pids = cst_iface.running_design_environments()
        first_de = None
        first_error = None

        for pid in pids:
            try:
                de = cst_iface.DesignEnvironment.connect(pid)
            except Exception as exc:  # noqa: BLE001
                first_error = first_error or exc
                continue
            first_de = first_de or de
            try:
                return de, de.get_open_project(project_path)
            except Exception as exc:  # noqa: BLE001
                first_error = first_error or exc
                continue

        de = first_de
        if de is None:
            if create_new_if_none:
                de = cst_iface.DesignEnvironment.connect_to_any_or_new()
            else:
                raise RuntimeError(
                    "No running CST DesignEnvironment found. "
                    "Please start CST Studio Suite manually first."
                )

        try:
            return de, de.open_project(project_path)
        except Exception as exc:  # noqa: BLE001
            detail = f"{exc}"
            if first_error is not None and str(first_error) not in detail:
                detail = f"{detail}; first open-project lookup error: {first_error}"
            raise RuntimeError(
                "Unable to open CST project in the connected "
                f"DesignEnvironment: {project_path}. {detail}"
            ) from exc

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

    def execute_inline_vba(self, vba_code: str) -> None:
        """Execute an inline VBA snippet without adding a model-history step."""
        if self.prj.schematic is None:
            raise RuntimeError(
                "Schematic interface is not available for this project."
            )
        self.prj.schematic.execute_vba_code(self._ensure_sub_main(vba_code))

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
            # CST's TOUCHSTONE.Write command is version/project sensitive
            # and can raise a modal "Touchstone export calculation failed"
            # dialog even when S-parameter results exist. Use the result-tree
            # ASCII export as the default reliable path; OpenClaw can still
            # plot and summarize the S11 curve from this CSV.
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
            "Dim leamPath As String\n"
            "Dim leamTreePath As String\n"
            "Dim leamIndex As Long\n"
            "Dim leamSigFile As String\n"
            "Dim leamResult As Object\n"
            "Dim leamN As Long\n"
            "Dim leamRe As Double\n"
            "Dim leamIm As Double\n"
            "Dim leamMag As Double\n"
            "Dim leamMagDb As Double\n"
            f'leamPath = "{quoted}"\n'
            'leamTreePath = "1D Results\\S-Parameters\\S1,1"\n'
            "leamSigFile = ResultTree.GetFileFromTreeItem(leamTreePath)\n"
            "If leamSigFile = \"\" Then\n"
            ' leamTreePath = "1D Results\\S-Parameters\\S1(1),1(1)"\n'
            " leamSigFile = ResultTree.GetFileFromTreeItem(leamTreePath)\n"
            "End If\n"
            "If leamSigFile = \"\" Then\n"
            ' Err.Raise vbObjectError + 901, "LEAM", "S11 result tree item was not found under 1D Results\\S-Parameters."\n'
            "End If\n"
            "Set leamResult = Result1DComplex(leamSigFile)\n"
            "Open leamPath For Output As #1\n"
            'Print #1, "frequency_ghz,s11_real,s11_imag,s11_mag_db"\n'
            "leamN = leamResult.GetN\n"
            "For leamIndex = 0 To leamN - 1\n"
            " leamRe = leamResult.GetYRe(leamIndex)\n"
            " leamIm = leamResult.GetYIm(leamIndex)\n"
            " leamMag = Sqr(leamRe * leamRe + leamIm * leamIm)\n"
            " If leamMag <= 0 Then\n"
            "  leamMagDb = -999\n"
            " Else\n"
            "  leamMagDb = 20 * Log(leamMag) / Log(10)\n"
            " End If\n"
            ' Print #1, Trim$(Str$(leamResult.GetX(leamIndex))) & "," & Trim$(Str$(leamRe)) & "," & Trim$(Str$(leamIm)) & "," & Trim$(Str$(leamMagDb))\n'
            "Next leamIndex\n"
            "Close #1\n"
        )
        self.execute_inline_vba(csv_code)

    # ---------------------------------------------------------------------
    # Optimizer helpers (CST Optimizer)
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

    def get_project_parameters(self) -> Dict[str, str]:
        """Return the open CST project's current ParameterList.

        This uses CST's Project object query API through a small VBA
        snippet because the Python wrapper does not expose a stable
        cross-version parameter-list accessor.
        """
        if self.prj is None:
            raise RuntimeError("No open CST project; cannot read parameters.")

        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            prefix="leam_parameters_",
            delete=False,
            encoding="utf-8",
        )
        output_path = handle.name
        handle.close()
        os.unlink(output_path)

        quoted = self._vba_quote(os.path.abspath(output_path))
        code = (
            "Dim leamPath As String\n"
            "Dim leamIndex As Long\n"
            "Dim leamCount As Long\n"
            "Dim leamName As String\n"
            "Dim leamExpr As String\n"
            f'leamPath = "{quoted}"\n'
            "Open leamPath For Output As #1\n"
            "leamCount = GetNumberOfParameters\n"
            "For leamIndex = 0 To leamCount - 1\n"
            " leamName = GetParameterName(leamIndex)\n"
            " leamExpr = GetParameterSValue(leamIndex)\n"
            ' Print #1, leamName & "=" & leamExpr\n'
            "Next leamIndex\n"
            "Close #1\n"
        )
        self.execute_inline_vba(code)

        values: Dict[str, str] = {}
        try:
            with open(output_path, "r", encoding="utf-8") as result_file:
                for raw_line in result_file:
                    line = raw_line.strip()
                    if not line or "=" not in line:
                        continue
                    name, value = line.split("=", 1)
                    name = name.strip()
                    value = value.strip()
                    if name:
                        values[name] = value
        finally:
            try:
                os.remove(output_path)
            except OSError:
                pass
        return values

    def get_optimizer_parameters(self) -> Dict[str, str]:
        """Return CST Optimizer's varying parameter values after a run.

        CST's Python wrapper does not consistently expose the Optimizer
        query methods across releases, so this emits a tiny VBA snippet
        that asks the Optimizer object for its varying-parameter table
        and writes it to a temporary text file.
        """
        if self.prj is None:
            raise RuntimeError("No open CST project; cannot read optimizer values.")

        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            prefix="leam_optimizer_",
            delete=False,
            encoding="utf-8",
        )
        output_path = handle.name
        handle.close()
        os.unlink(output_path)

        quoted = self._vba_quote(os.path.abspath(output_path))
        code = (
            "Dim leamPath As String\n"
            "Dim leamIndex As Long\n"
            "Dim leamCount As Long\n"
            "Dim leamName As String\n"
            "Dim leamValue As Double\n"
            f'leamPath = "{quoted}"\n'
            "Open leamPath For Output As #1\n"
            "With Optimizer\n"
            " leamCount = .GetNumberOfVaryingParameters\n"
            " For leamIndex = 0 To leamCount - 1\n"
            "  leamName = .GetNameOfVaryingParameter(leamIndex)\n"
            "  leamValue = .GetValueOfVaryingParameter(leamIndex)\n"
            '  Print #1, leamName & "=" & CStr(leamValue)\n'
            " Next leamIndex\n"
            "End With\n"
            "Close #1\n"
        )
        self.execute_inline_vba(code)

        values: Dict[str, str] = {}
        try:
            with open(output_path, "r", encoding="utf-8") as result_file:
                for raw_line in result_file:
                    line = raw_line.strip()
                    if not line or "=" not in line:
                        continue
                    name, value = line.split("=", 1)
                    name = name.strip()
                    value = value.strip()
                    if name:
                        values[name] = value
        finally:
            try:
                os.remove(output_path)
            except OSError:
                pass
        return values

    @staticmethod
    def _optimizer_type_token(algorithm: str) -> str:
        mapping = {
            "Trust Region Framework": "Trust_Region",
            "Nelder Mead Simplex": "Nelder_Mead_Simplex",
            "Interpolated Quasi Newton": "Interpolated_NR_VariableMetric",
            "Classic Powell": "Classic_Powell",
            "Genetic Algorithm": "Genetic_Algorithm",
            "Particle Swarm Optimization": "Particle_Swarm",
        }
        return mapping.get(str(algorithm).strip(), str(algorithm).strip())

    def configure_optimizer(
        self,
        *,
        variables: List[Dict[str, Any]],
        goals_vba: List[str],
        algorithm: str = "Nelder Mead Simplex",
        max_evaluations: int = 40,
        max_iterations: Optional[int] = None,
        population_size: Optional[int] = None,
        optimizer_budget: Optional[Dict[str, Any]] = None,
        use_current_as_init: bool = True,
    ) -> None:
        """Emit the VBA that configures CST's Optimizer for this run.

        ``variables`` is a list of dicts like
        ``{"name": "L", "min": 10.0, "max": 20.0, "init": 15.0}``.
        The ``init`` value is optional; when omitted CST uses whatever
        value is already in ParameterList.
        """
        if self.prj is None:
            raise RuntimeError("No open CST project; cannot configure optimizer.")

        optimizer_type = self._optimizer_type_token(algorithm)
        bool_text = "True" if use_current_as_init else "False"
        lines: List[str] = [
            "With Optimizer",
            f' .SetOptimizerType "{self._vba_quote(optimizer_type)}"',
            " .StartActiveSolver True",
            " .InitParameterList",
            " .ResetParameterList",
            f" .SetAlwaysStartFromCurrent {bool_text}",
            " .SetGoalSummaryType \"Sum_All_Goals\"",
            " .SetUseDataOfPreviousCalculations False",
            " .DeleteAllGoals",
        ]
        budget = optimizer_budget or {}
        effective_iterations = max_iterations or budget.get("max_iterations")
        effective_population = population_size or budget.get("population_size")

        if optimizer_type in {"Trust_Region", "Nelder_Mead_Simplex"}:
            lines.append(f' .SetUseMaxEval True, "{optimizer_type}"')
            lines.append(f' .SetMaxEval {int(max_evaluations)}, "{optimizer_type}"')
        elif optimizer_type in {"Genetic_Algorithm", "Particle_Swarm"}:
            if effective_iterations is None or effective_population is None:
                raise RuntimeError(
                    "Population optimizer requires max_iterations and "
                    "population_size from optimizer_budget."
                )
            lines.append(f' .SetGenerationSize {int(effective_population)}, "{optimizer_type}"')
            lines.append(f' .SetMaxIt {int(effective_iterations)}, "{optimizer_type}"')
        for var in variables:
            name = self._vba_quote(str(var["name"]))
            vmin = self._vba_quote(str(var["min"]))
            vmax = self._vba_quote(str(var["max"]))
            lines.append(f' .SelectParameter "{name}", True')
            if "init" in var and var["init"] is not None:
                init = self._vba_quote(str(var["init"]))
                lines.append(f" .SetParameterInit {init}")
            lines.append(f" .SetParameterMin {vmin}")
            lines.append(f" .SetParameterMax {vmax}")
            lines.append(" .SetParameterAnchors 5")
        lines.append("End With")
        lines.append("")

        vba = "\n".join(lines)
        with self._quiet_context():
            self.execute_inline_vba(vba)
            for goal_snippet in goals_vba:
                self.execute_inline_vba(goal_snippet)

    def run_optimizer(self) -> None:
        """Start CST's Optimizer synchronously.

        CST blocks the call until the optimization run completes (same
        behaviour as ``Solver.Start``). The method does not return
        best-so-far values; use :meth:`get_parameter` after the call.
        """
        if self.prj is None:
            raise RuntimeError("No open CST project; cannot run optimizer.")
        start_snippet = "With Optimizer\n .Start\nEnd With\n"
        with self._quiet_context():
            self.execute_inline_vba(start_snippet)
