"""OpenClaw-facing service facade for LEAM.

This module is the single import point OpenClaw needs. It exposes the
high-level entries on top of the existing workflows:

- ``build_and_simulate`` — dispatches to template / new / rerun pipelines
  based on the structured request, always headless.
- ``get_project_context_snapshot`` — returns the parameter list, the
  last simulation summary, and the goal-template / algorithm whitelists
  so OpenClaw can ground its NL → structured-request extraction.
- ``validate_optimization_request`` — the NL → structured-request
  defense line: strict schema validation, parameter cross-check against
  the project's ParameterList, unit normalization.
- ``optimize_parameters`` — invoke CST's optimizer on an existing
  project. Runs the same validation first and short-circuits with
  ``status="failed"`` when the request is invalid.

LEAM does no natural-language intent classification here. OpenClaw is
responsible for turning user utterances into a structured request
object; LEAM only executes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .infrastructure import (
    CstGateway,
    OutputRepository,
    read_run_record,
    write_run_record,
)
from .models import SessionPaths
from .services.optimization_goals import GoalPlan, GOAL_TEMPLATES, build_goal_plan
from .services.optimization_validation_service import (
    ALLOWED_ALGORITHMS,
    DEFAULT_ALGORITHM,
    GOAL_SCHEMA,
    OptimizationValidationService,
)
from .services.parameter_service import ParameterService
from .templates import TemplateRunner
from .workflows.contracts import (
    DESIGN_MODES,
    EXECUTION_MODES,
    WORKFLOW_EXECUTION_MODES,
)
from .workflows.new_design_workflow import NewDesignWorkflow
from .workflows.rerun_workflow import RerunWorkflow
from .workflows.template_workflow import TemplateWorkflow


# ---------------------------------------------------------------------------
# Request / result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BuildAndSimulateRequest:
    """Structured input for :meth:`LeamService.build_and_simulate`.

    Exactly one of (``description``, ``base_name``) must be supplied:

    - ``description`` + ``output_name`` → new or template pipeline
    - ``base_name`` → rerun an existing output directory

    ``execution_mode`` accepts the same values as
    :data:`leam.workflows.contracts.EXECUTION_MODES`:
    ``build_only`` / ``simulate_and_export`` / ``simulate_only``.
    """

    description: str = ""
    output_name: str = ""
    base_name: str = ""
    design_mode: str = "strong"
    execution_mode: str = "simulate_and_export"
    simulation_request: str = ""
    run_cst: bool = True
    prefer_template: bool = True
    enable_topology_check: bool = True


@dataclass
class BuildAndSimulateResult:
    """Structured output returned from :meth:`LeamService.build_and_simulate`."""

    workflow: str  # "template" | "new" | "rerun"
    output_name: str
    output_dir: str
    execution_mode: str
    matched_template: bool = False
    template_id: Optional[str] = None
    paths: Dict[str, str] = field(default_factory=dict)
    run_record_path: Optional[str] = None
    manifest_path: Optional[str] = None
    simulation_audit_path: Optional[str] = None
    touchstone_path: Optional[str] = None
    s11_csv_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OptimizationRequest:
    """Structured optimization request handed down from OpenClaw.

    - ``output_name`` points at an existing LEAM output directory that
      already contains a built ``.cst`` project.
    - ``variables`` is a list of dicts shaped
      ``{"name": str, "min": float, "max": float, "init": float?}``.
    - ``goals`` is a list of ``{"template": str, "args": {...}}`` items
      drawn from :data:`leam.services.GOAL_TEMPLATES`.
    - ``algorithm`` defaults to Nelder Mead Simplex because geometry-sensitive
      CST models can abort early with Trust Region after a single bad point.
      Any whitelisted CST optimizer string can still be passed explicitly.
    - ``max_evaluations`` is the total solver-run budget OpenClaw must confirm
      with the user. For PSO/GA, LEAM converts it into ``max_iterations`` and
      ``population_size`` and returns the effective ``optimizer_budget`` from
      validation.

    Strict validation (required fields, range checks, unit handling) is
    applied by :class:`~leam.services.OptimizationValidationService`
    which is invoked both by ``validate_optimization_request`` and
    ``optimize_parameters``; this dataclass stays permissive so OpenClaw
    can build it directly from its JSON parser output.
    """

    output_name: str
    variables: List[Dict[str, Any]] = field(default_factory=list)
    goals: List[Dict[str, Any]] = field(default_factory=list)
    algorithm: str = DEFAULT_ALGORITHM
    max_evaluations: int = 40
    max_iterations: Optional[int] = None
    population_size: Optional[int] = None
    use_current_as_init: bool = True
    natural_language: str = ""
    notes: str = ""


@dataclass
class OptimizationValidationResult:
    is_valid: bool
    normalized: Optional[Dict[str, Any]] = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectContextSnapshot:
    """Point-in-time view of a LEAM output directory for OpenClaw.

    OpenClaw calls this before extracting an optimization request from
    the user so it can ground the LLM prompt in real data (parameter
    names, last simulation frequency band, unit conventions). The
    snapshot is read-only: it never touches CST and never mutates the
    output dir.
    """

    output_name: str
    output_dir: str
    exists: bool
    has_cst_project: bool
    has_parameters_bas: bool
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    last_simulation: Dict[str, Any] = field(default_factory=dict)
    goal_templates: List[Dict[str, Any]] = field(default_factory=list)
    algorithms: List[str] = field(default_factory=list)
    units: Dict[str, str] = field(default_factory=dict)
    schema_hint: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OptimizationResult:
    output_name: str
    status: str  # "success" | "failed" | "skipped"
    best_parameters: Dict[str, Any] = field(default_factory=dict)
    optimization_manifest_path: Optional[str] = None
    optimization_audit_path: Optional[str] = None
    best_parameters_path: Optional[str] = None
    history_path: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParameterUpdateRequest:
    """Explicit parameter patch request from OpenClaw.

    This is for the post-simulation / post-optimization loop where the
    user says something concrete such as "set Lp to 28.5 mm to pull the
    resonance lower". OpenClaw owns NL understanding and memory; LEAM
    applies the already-structured patch to the existing generated files
    without calling the design-generation pipeline again.
    """

    output_name: str
    updates: Dict[str, Any] = field(default_factory=dict)
    purpose: str = ""
    natural_language: str = ""
    notes: str = ""


@dataclass
class ParameterUpdateResult:
    output_name: str
    status: str  # "success" | "failed"
    changed_parameters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    updated_files: Dict[str, str] = field(default_factory=dict)
    audit_path: Optional[str] = None
    run_record_path: Optional[str] = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Service facade
# ---------------------------------------------------------------------------


class LeamService:
    """High-level LEAM entry for OpenClaw."""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = Path(project_root) if project_root else _default_project_root()
        self._output_repo = OutputRepository(self.project_root)

    # ---- build & simulate -------------------------------------------------

    def build_and_simulate(
        self, request: BuildAndSimulateRequest
    ) -> BuildAndSimulateResult:
        """Route to template / new / rerun pipeline and return a structured result."""
        self._validate_request(request)

        if request.base_name:
            return self._run_rerun(request)

        matched = None
        if request.prefer_template:
            matched = self._try_template_match(request.description)

        if matched is not None:
            return self._run_template(request, matched)

        return self._run_new_then_simulate(request)

    def list_templates(self) -> List[Dict[str, Any]]:
        """Return template metadata that OpenClaw can display or use for routing."""
        runner = TemplateRunner()
        metas = runner.list_templates()
        return [
            {
                "template_id": meta.template_id,
                "name": meta.name,
                "version": meta.version,
                "antenna_type": meta.antenna_type,
                "substrate": meta.substrate,
                "baseline_frequency_ghz": meta.baseline_frequency_ghz,
                "match_keywords": list(meta.match_keywords),
                "match_substrate": list(meta.match_substrate),
                "editable_params": list(meta.editable_params),
                "locked_params": list(meta.locked_params),
            }
            for meta in metas
        ]

    # ---- optimization ------------------------------------------------------

    def get_project_context_snapshot(
        self, output_name: str
    ) -> ProjectContextSnapshot:
        """Return a read-only view OpenClaw can inject into its prompt.

        The snapshot is intentionally compact and JSON-safe so OpenClaw
        can hand it to the LLM as grounding context: parameter names
        (so the model cannot invent new variable names), last
        simulation frequency range (so it picks sensible goal ranges),
        the whitelisted goal templates + required args, and the
        supported algorithm names.
        """
        if not output_name or not str(output_name).strip():
            raise ValueError("output_name is required for project context snapshot")

        dir_existed = self._probe_output_dir(output_name)
        paths = self._resolve_paths_readonly(output_name)
        assert paths is not None  # guarded by the check above
        has_cst = paths.cst.exists()
        has_params = paths.parameters.exists()
        output_dir_exists = dir_existed or has_cst or has_params

        parameters = self._read_parameters_snapshot(paths)
        last_simulation = self._read_last_simulation(paths)

        return ProjectContextSnapshot(
            output_name=output_name,
            output_dir=str(paths.output_dir),
            exists=output_dir_exists,
            has_cst_project=has_cst,
            has_parameters_bas=has_params,
            parameters=parameters,
            last_simulation=last_simulation,
            goal_templates=_goal_templates_for_snapshot(),
            algorithms=list(ALLOWED_ALGORITHMS),
            units={"length": "mm", "frequency": "GHz"},
            schema_hint=_optimization_schema_hint(),
        )

    def validate_optimization_request(
        self, request: OptimizationRequest
    ) -> OptimizationValidationResult:
        """Validate without executing. OpenClaw calls this before user confirm."""
        dir_existed = self._probe_output_dir(request.output_name)
        paths = self._resolve_paths_readonly(request.output_name)
        parameters_bas = paths.parameters if paths is not None else None

        service = OptimizationValidationService(project_root=self.project_root)
        report = service.validate(_request_to_dict(request), parameters_bas=parameters_bas)

        if paths is not None:
            project_errors, project_warnings = _check_project_availability(
                paths, request.output_name, dir_existed=dir_existed
            )
            report["errors"].extend(project_errors)
            report["warnings"].extend(project_warnings)
            if project_errors:
                report["is_valid"] = False

        return OptimizationValidationResult(
            is_valid=report["is_valid"],
            normalized=report["normalized"],
            errors=report["errors"],
            warnings=report["warnings"],
        )

    def optimize_parameters(self, request: OptimizationRequest) -> OptimizationResult:
        """Run CST's Optimizer1D on an existing LEAM output project.

        The request is validated up-front through
        :class:`OptimizationValidationService`; invalid requests return
        a structured ``status="failed"`` result instead of raising so
        OpenClaw can surface the specific error codes to the user.
        """
        validation = self.validate_optimization_request(request)
        if not validation.is_valid:
            return OptimizationResult(
                output_name=request.output_name or "",
                status="failed",
                error="validation_failed",
                best_parameters={},
                optimization_manifest_path=None,
                optimization_audit_path=None,
                best_parameters_path=None,
                history_path=None,
            )

        normalized = validation.normalized or {}
        paths = self._output_repo.build_paths(request.output_name)

        variables = normalized.get("variables") or request.variables
        goals = normalized.get("goals") or request.goals
        algorithm = normalized.get("algorithm") or request.algorithm
        max_evaluations = normalized.get("max_evaluations") or request.max_evaluations
        max_iterations = normalized.get("max_iterations")
        population_size = normalized.get("population_size")
        optimizer_budget = normalized.get("optimizer_budget") or {}

        goal_plans: List[GoalPlan] = [
            build_goal_plan(g["template"], g.get("args", {})) for g in goals
        ]

        gateway = CstGateway()
        try:
            manifest = gateway.run_optimization(
                paths=paths,
                variables=variables,
                goals=goal_plans,
                algorithm=algorithm,
                max_evaluations=max_evaluations,
                max_iterations=max_iterations,
                population_size=population_size,
                optimizer_budget=optimizer_budget,
                use_current_as_init=request.use_current_as_init,
                nl_request=request.natural_language,
                parsed_request={
                    "variables": variables,
                    "goals": goals,
                    "algorithm": algorithm,
                    "max_evaluations": max_evaluations,
                    "max_iterations": max_iterations,
                    "population_size": population_size,
                    "optimizer_budget": optimizer_budget,
                    "notes": request.notes,
                },
            )
            status = manifest.get("status", "success")
            error = manifest.get("error")
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error = str(exc)
            manifest = None

        best: Dict[str, Any] = {}
        if paths.best_parameters.exists():
            try:
                loaded = json.loads(paths.best_parameters.read_text(encoding="utf-8"))
                best = loaded.get("parameters", {}) if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                best = {}

        return OptimizationResult(
            output_name=request.output_name,
            status=status,
            best_parameters=best,
            optimization_manifest_path=(
                str(paths.optimization_manifest)
                if paths.optimization_manifest.exists()
                else None
            ),
            optimization_audit_path=(
                str(paths.optimization_audit)
                if paths.optimization_audit.exists()
                else None
            ),
            best_parameters_path=(
                str(paths.best_parameters) if paths.best_parameters.exists() else None
            ),
            history_path=(
                str(paths.optimization_history_csv)
                if paths.optimization_history_csv.exists()
                else None
            ),
            error=error,
        )

    # ---- explicit parameter edits -----------------------------------------

    def apply_parameter_updates(
        self, request: ParameterUpdateRequest
    ) -> ParameterUpdateResult:
        """Patch generated parameter artifacts without regenerating via LEAM.

        Only existing ParameterList names are accepted. The method updates
        ``<name>_parameters.bas`` and any generated JSON artifact containing
        a ``parameters`` object. Other generated BAS files normally reference
        the parameter names rather than copying numeric values, so they remain
        valid and are reported as scanned/no-op in the audit.
        """
        name = (request.output_name or "").strip()
        if not name:
            return _parameter_update_failed(
                request.output_name,
                "OUTPUT_NAME_REQUIRED",
                "output_name",
                "output_name is required.",
            )

        dir_existed = self._probe_output_dir(name)
        paths = self._resolve_paths_readonly(name)
        if paths is None or not dir_existed:
            return _parameter_update_failed(
                name,
                "PROJECT_MISSING",
                "output_name",
                f"Output directory {name!r} does not exist.",
            )
        if not paths.parameters.exists():
            return _parameter_update_failed(
                name,
                "PARAMETERS_BAS_MISSING",
                "output_name",
                f"{paths.parameters.name} does not exist.",
            )

        updates = _normalize_parameter_updates(request.updates)
        if not updates:
            return _parameter_update_failed(
                name,
                "UPDATES_REQUIRED",
                "updates",
                "At least one parameter update is required.",
            )

        try:
            params = ParameterService.parse_bas(paths.parameters.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            return _parameter_update_failed(
                name,
                "PARAMETERS_BAS_UNREADABLE",
                "output_name",
                str(exc),
            )

        by_lower = {p["name"].lower(): p for p in params}
        errors: List[Dict[str, Any]] = []
        for param_name in updates:
            if param_name.lower() not in by_lower:
                errors.append(
                    {
                        "code": "PARAMETER_UNKNOWN",
                        "field": f"updates.{param_name}",
                        "message": f"Parameter {param_name!r} is not in ParameterList.",
                        "suggestion": "Call get_project_context_snapshot and choose one of the returned parameter names.",
                    }
                )
        if errors:
            return ParameterUpdateResult(
                output_name=name,
                status="failed",
                errors=errors,
            )

        changed: Dict[str, Dict[str, Any]] = {}
        canonical_updates: Dict[str, str] = {}
        for requested_name, value in updates.items():
            param = by_lower[requested_name.lower()]
            canonical = param["name"]
            old_value = param.get("value", "")
            new_value = _format_parameter_value(value)
            if str(old_value) != new_value:
                param["value"] = new_value
                changed[canonical] = {
                    "old": old_value,
                    "new": new_value,
                }
            canonical_updates[canonical] = new_value

        if not changed:
            return ParameterUpdateResult(
                output_name=name,
                status="success",
                changed_parameters={},
                warnings=[
                    {
                        "code": "NO_PARAMETER_VALUE_CHANGED",
                        "field": "updates",
                        "message": "All requested parameters already had the requested values.",
                    }
                ],
            )

        updated_files: Dict[str, str] = {}
        paths.parameters.write_text(ParameterService.to_bas(params), encoding="utf-8")
        updated_files["parameters_bas"] = str(paths.parameters)

        for label, path in (
            ("solids_json", paths.json),
            ("dimensions_json", paths.dimensions),
        ):
            if _patch_json_parameters(path, canonical_updates):
                updated_files[label] = str(path)

        audit_path = _write_parameter_update_audit(
            paths=paths,
            request=request,
            changed=changed,
            updated_files=updated_files,
        )
        run_record_path = _refresh_run_record_after_parameter_update(
            paths=paths,
            output_name=name,
            request=request,
            audit_path=audit_path,
        )

        return ParameterUpdateResult(
            output_name=name,
            status="success",
            changed_parameters=changed,
            updated_files=updated_files,
            audit_path=str(audit_path),
            run_record_path=str(run_record_path),
        )

    def _resolve_paths_readonly(self, output_name: str) -> Optional[SessionPaths]:
        """Build ``SessionPaths`` without the mkdir side-effect.

        Read-only flows (``validate_optimization_request`` and
        ``get_project_context_snapshot``) MUST use this instead of
        :meth:`OutputRepository.build_paths` so a stray call cannot
        auto-materialize a directory for a project that does not exist
        yet.
        """
        name = (output_name or "").strip()
        if not name:
            return None
        session_dir = self.project_root / "examples" / "output" / name
        return SessionPaths.build(session_dir, name)

    def _probe_output_dir(self, output_name: str) -> bool:
        """Return True if the output dir already existed on disk."""
        name = (output_name or "").strip()
        if not name:
            return False
        return (self.project_root / "examples" / "output" / name).exists()

    @staticmethod
    def _read_parameters_snapshot(paths: SessionPaths) -> List[Dict[str, Any]]:
        if not paths.parameters.exists():
            return []
        try:
            text = paths.parameters.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        return [
            {
                "name": p.get("name", ""),
                "value": p.get("value", ""),
                "comment": p.get("comment", ""),
            }
            for p in ParameterService.parse_bas(text)
            if p.get("name")
        ]

    @staticmethod
    def _read_last_simulation(paths: SessionPaths) -> Dict[str, Any]:
        record = read_run_record(paths.output_dir)
        if record is None:
            return {}
        sim = (record.get("simulation") or {}) if isinstance(record, dict) else {}
        artifacts = (record.get("artifacts") or {}) if isinstance(record, dict) else {}
        s11 = artifacts.get("s11_touchstone") if isinstance(artifacts, dict) else None
        summary: Dict[str, Any] = {
            "status": sim.get("status") if isinstance(sim, dict) else None,
            "request": (
                record.get("execution", {}).get("simulation_request")
                if isinstance(record.get("execution"), dict)
                else None
            ),
            "frequency": sim.get("frequency") if isinstance(sim, dict) else None,
            "s11_touchstone": s11.get("path") if isinstance(s11, dict) else None,
            "run_record_schema_version": record.get("schema_version"),
        }
        return {k: v for k, v in summary.items() if v is not None}

    # ---- internals --------------------------------------------------------

    def _run_rerun(self, request: BuildAndSimulateRequest) -> BuildAndSimulateResult:
        rerun_allowed = WORKFLOW_EXECUTION_MODES["rerun"]
        if request.execution_mode not in rerun_allowed:
            exec_mode = "simulate_only" if request.run_cst else "build_only"
        else:
            exec_mode = request.execution_mode
        workflow = RerunWorkflow(self.project_root)
        workflow.run(
            base_name=request.base_name,
            run_cst=request.run_cst,
            execution_mode=exec_mode,
            simulation_request=request.simulation_request,
        )
        paths = self._output_repo.build_paths(request.base_name)
        return self._finalize_result(
            workflow="rerun",
            output_name=request.base_name,
            execution_mode=exec_mode,
            run_cst=request.run_cst,
            paths=paths,
            matched_template=False,
            template_id=None,
            description="",
            simulation_request=request.simulation_request,
        )

    def _run_template(
        self,
        request: BuildAndSimulateRequest,
        matched: Any,
    ) -> BuildAndSimulateResult:
        template, match_result = matched  # noqa: F841 — match_result already in cache
        template_allowed = WORKFLOW_EXECUTION_MODES["template"]
        exec_mode = (
            request.execution_mode
            if request.execution_mode in template_allowed
            else "simulate_and_export"
            if request.run_cst and request.simulation_request
            else "build_only"
        )
        output_name = request.output_name or _default_output_name()
        workflow = TemplateWorkflow(self.project_root)
        result = workflow.run(
            description=request.description,
            output_name=output_name,
            run_cst=request.run_cst,
            execution_mode=exec_mode,
            simulation_request=request.simulation_request,
            skip_review=True,
        )
        paths = self._output_repo.build_paths(output_name)
        return self._finalize_result(
            workflow="template",
            output_name=output_name,
            execution_mode=exec_mode,
            run_cst=request.run_cst,
            paths=paths,
            matched_template=bool(result.get("matched", True)),
            template_id=result.get("template_id"),
            description=request.description,
            simulation_request=request.simulation_request,
        )

    def _run_new_then_simulate(
        self, request: BuildAndSimulateRequest
    ) -> BuildAndSimulateResult:
        output_name = request.output_name or _default_output_name()
        workflow = NewDesignWorkflow(self.project_root)
        session = workflow.build_session(
            description=request.description,
            mode=request.design_mode,
            output_name=output_name,
        )
        # NewDesignWorkflow's contract only allows build_only.
        workflow.run(
            session,
            run_cst=request.run_cst,
            execution_mode="build_only",
            simulation_request="",
            enable_topology_check=request.enable_topology_check,
        )

        # Chain a rerun simulate pass if the caller asked for simulation.
        exec_mode = "build_only"
        if (
            request.run_cst
            and request.execution_mode in ("simulate_and_export", "simulate_only")
        ):
            rerun = RerunWorkflow(self.project_root)
            rerun.run(
                base_name=output_name,
                run_cst=True,
                execution_mode="simulate_only",
                simulation_request=request.simulation_request,
            )
            exec_mode = "simulate_and_export"

        paths = self._output_repo.build_paths(output_name)
        return self._finalize_result(
            workflow="new",
            output_name=output_name,
            execution_mode=exec_mode,
            run_cst=request.run_cst,
            paths=paths,
            matched_template=False,
            template_id=None,
            description=request.description,
            simulation_request=request.simulation_request,
        )

    def _try_template_match(self, description: str):
        if not description.strip():
            return None
        runner = TemplateRunner()
        return runner.match(description)

    @staticmethod
    def _finalize_result(
        *,
        workflow: str,
        output_name: str,
        execution_mode: str,
        run_cst: bool,
        paths: SessionPaths,
        matched_template: bool,
        template_id: Optional[str],
        description: str,
        simulation_request: str,
    ) -> BuildAndSimulateResult:
        def _maybe(path: Path) -> Optional[str]:
            return str(path) if path.exists() else None

        record_path = write_run_record(
            paths=paths,
            workflow=workflow,
            output_name=output_name,
            execution_mode=execution_mode,
            run_cst=run_cst,
            description=description,
            template_id=template_id,
            matched_template=matched_template,
            simulation_request=simulation_request,
        )

        return BuildAndSimulateResult(
            workflow=workflow,
            output_name=output_name,
            output_dir=str(paths.output_dir),
            execution_mode=execution_mode,
            matched_template=matched_template,
            template_id=template_id,
            paths={
                "json": str(paths.json),
                "parameters": str(paths.parameters),
                "dimensions": str(paths.dimensions),
                "materials": str(paths.materials),
                "model": str(paths.model),
                "boolean": str(paths.boolean),
                "cst": str(paths.cst),
            },
            run_record_path=str(record_path),
            manifest_path=_maybe(paths.manifest),
            simulation_audit_path=_maybe(paths.simulation_audit),
            touchstone_path=_maybe(paths.s11_touchstone),
            s11_csv_path=_maybe(paths.s11_csv),
        )

    @staticmethod
    def _validate_request(request: BuildAndSimulateRequest) -> None:
        if not request.base_name and not request.description:
            raise ValueError(
                "BuildAndSimulateRequest requires either description "
                "(for new/template) or base_name (for rerun)."
            )
        if request.base_name and request.description:
            raise ValueError(
                "BuildAndSimulateRequest must not set both description and "
                "base_name; rerun does not use description."
            )
        if request.execution_mode not in EXECUTION_MODES:
            allowed = ", ".join(EXECUTION_MODES)
            raise ValueError(
                f"execution_mode must be one of: {allowed}; "
                f"got {request.execution_mode!r}"
            )
        if request.design_mode not in DESIGN_MODES:
            allowed = ", ".join(DESIGN_MODES)
            raise ValueError(
                f"design_mode must be one of: {allowed}; "
                f"got {request.design_mode!r}"
            )


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def build_and_simulate(
    request: BuildAndSimulateRequest,
    *,
    project_root: Optional[Path] = None,
) -> BuildAndSimulateResult:
    return LeamService(project_root).build_and_simulate(request)


def validate_optimization_request(
    request: OptimizationRequest,
    *,
    project_root: Optional[Path] = None,
) -> OptimizationValidationResult:
    return LeamService(project_root).validate_optimization_request(request)


def optimize_parameters(
    request: OptimizationRequest,
    *,
    project_root: Optional[Path] = None,
) -> OptimizationResult:
    return LeamService(project_root).optimize_parameters(request)


def apply_parameter_updates(
    request: ParameterUpdateRequest,
    *,
    project_root: Optional[Path] = None,
) -> ParameterUpdateResult:
    return LeamService(project_root).apply_parameter_updates(request)


def list_templates(*, project_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    return LeamService(project_root).list_templates()


def get_project_context_snapshot(
    output_name: str,
    *,
    project_root: Optional[Path] = None,
) -> ProjectContextSnapshot:
    return LeamService(project_root).get_project_context_snapshot(output_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request_to_dict(request: OptimizationRequest) -> Dict[str, Any]:
    return {
        "output_name": request.output_name,
        "variables": list(request.variables or []),
        "goals": list(request.goals or []),
        "algorithm": request.algorithm,
        "max_evaluations": request.max_evaluations,
        "max_iterations": request.max_iterations,
        "population_size": request.population_size,
        "use_current_as_init": request.use_current_as_init,
        "natural_language": request.natural_language,
        "notes": request.notes,
    }


def _normalize_parameter_updates(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return {str(k).strip(): v for k, v in raw.items() if str(k).strip()}
    if isinstance(raw, list):
        updates: Dict[str, Any] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if name and "value" in item:
                updates[name] = item["value"]
        return updates
    return {}


def _format_parameter_value(value: Any) -> str:
    text = str(value).strip()
    text = text.replace("：", ":")
    for suffix in ("mm", "GHz", "MHz", "kHz", "Hz", "mil"):
        if text.lower().endswith(suffix.lower()):
            return text[: -len(suffix)].strip()
    return text


def _json_safe_parameter_value(value: str) -> Any:
    try:
        return int(value) if value.isdigit() else float(value)
    except ValueError:
        return value


def _patch_json_parameters(path: Path, updates: Dict[str, str]) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False

    changed = False

    def visit(node: Any) -> None:
        nonlocal changed
        if isinstance(node, dict):
            params = node.get("parameters")
            if isinstance(params, dict):
                lower_to_key = {str(k).lower(): k for k in params}
                for name, value in updates.items():
                    existing_key = lower_to_key.get(name.lower())
                    if existing_key is not None:
                        new_value = _json_safe_parameter_value(value)
                        if params.get(existing_key) != new_value:
                            params[existing_key] = new_value
                            changed = True
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
    if not changed:
        return False
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _write_parameter_update_audit(
    *,
    paths: SessionPaths,
    request: ParameterUpdateRequest,
    changed: Dict[str, Dict[str, Any]],
    updated_files: Dict[str, str],
) -> Path:
    audit_dir = paths.results_dir / "parameter_updates"
    audit_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    audit_path = audit_dir / f"{stamp}.json"
    payload = {
        "schema_version": "1.0",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "explicit_parameter_update",
        "output_name": request.output_name,
        "purpose": request.purpose or "",
        "natural_language": request.natural_language or "",
        "notes": request.notes or "",
        "requested_updates": dict(request.updates or {}),
        "changed_parameters": changed,
        "updated_files": updated_files,
        "scanned_noop_files": {
            "materials_bas": str(paths.materials),
            "model_bas": str(paths.model),
            "boolean_bas": str(paths.boolean),
        },
    }
    audit_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return audit_path


def _refresh_run_record_after_parameter_update(
    *,
    paths: SessionPaths,
    output_name: str,
    request: ParameterUpdateRequest,
    audit_path: Path,
) -> Path:
    existing = read_run_record(paths.output_dir) or {}
    record_path = write_run_record(
        paths=paths,
        workflow=existing.get("workflow") or "parameter_update",
        output_name=output_name,
        execution_mode=existing.get("execution_mode") or "build_only",
        run_cst=bool(existing.get("run_cst", False)),
        description=existing.get("description") or "",
        template_id=(existing.get("template") or {}).get("template_id")
        if isinstance(existing.get("template"), dict)
        else None,
        matched_template=bool((existing.get("template") or {}).get("matched"))
        if isinstance(existing.get("template"), dict)
        else False,
        simulation_request=existing.get("simulation_request") or "",
    )
    record = read_run_record(paths.output_dir) or {}
    record["last_parameter_update"] = {
        "audit_path": str(audit_path),
        "purpose": request.purpose or "",
        "natural_language": request.natural_language or "",
    }
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return record_path


def _parameter_update_failed(
    output_name: str,
    code: str,
    field: str,
    message: str,
) -> ParameterUpdateResult:
    return ParameterUpdateResult(
        output_name=output_name or "",
        status="failed",
        errors=[{"code": code, "field": field, "message": message}],
    )


def _check_project_availability(
    paths: SessionPaths,
    output_name: str,
    *,
    dir_existed: bool,
) -> tuple:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    if not dir_existed:
        errors.append(
            {
                "code": "PROJECT_MISSING",
                "field": "output_name",
                "message": (
                    f"未找到输出目录 {output_name!r}，无法优化。"
                ),
                "suggestion": "先用 build_and_simulate 生成一次，再复用其 output_name。",
            }
        )
        return errors, warnings
    if not paths.cst.exists():
        errors.append(
            {
                "code": "CST_PROJECT_MISSING",
                "field": "output_name",
                "message": (
                    f".cst 工程不存在: {paths.cst}。优化器只能在已构建的工程上跑。"
                ),
                "suggestion": "先跑 build_and_simulate(run_cst=True) 生成 .cst。",
            }
        )
    if not paths.parameters.exists():
        warnings.append(
            {
                "code": "PARAMETERS_BAS_MISSING",
                "field": "output_name",
                "message": (
                    f"{paths.parameters.name} 不存在，变量名白名单将无法执行。"
                ),
                "suggestion": "确认 build_and_simulate 完成并写出参数 BAS。",
            }
        )
    return errors, warnings


def _goal_templates_for_snapshot() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for template in GOAL_TEMPLATES:
        schema = GOAL_SCHEMA.get(template, {})
        entries.append(
            {
                "template": template,
                "description": schema.get("description", ""),
                "required_args": list(schema.get("required", ())),
                "optional_args": list(schema.get("optional", ())),
                "defaults": dict(schema.get("defaults", {})),
            }
        )
    return entries


def _optimization_schema_hint() -> Dict[str, Any]:
    """Return a stable JSON-shape hint OpenClaw mirrors in its prompt."""
    return {
        "output_name": "string (existing LEAM output directory)",
        "variables": [
            {
                "name": "string (must be in ParameterList)",
                "min": "number",
                "max": "number",
                "init": "number (optional, within [min, max])",
            }
        ],
        "goals": [
            {
                "template": f"one of {list(GOAL_TEMPLATES)}",
                "args": "object matching the template's required/optional args",
            }
        ],
        "algorithm": f"one of {list(ALLOWED_ALGORITHMS)} (default {DEFAULT_ALGORITHM!r})",
        "max_evaluations": "integer 1-500 total solver-run budget (default 40)",
        "max_iterations": "optional integer for Particle Swarm / Genetic Algorithm iterations",
        "population_size": "optional integer for Particle Swarm particles / Genetic Algorithm population",
        "optimizer_budget": "returned by validation; OpenClaw must show estimated_solver_runs and get user confirmation before execution",
        "use_current_as_init": "boolean (default true)",
        "natural_language": "string (raw user utterance, optional)",
        "notes": "string (extra OpenClaw-side annotations, optional)",
    }


def _default_project_root() -> Path:
    """Return the repository root that contains ``examples/output``.

    Walks up from this file first, then falls back to ``cwd``. This
    keeps LEAM usable both as an installed package in OpenClaw's venv
    and from the LEAM repository itself.
    """
    here = Path(__file__).resolve()
    for candidate in [here.parent.parent.parent, *here.parents]:
        if (candidate / "examples").exists() or (candidate / "src").exists():
            return candidate
    return Path.cwd()


def _default_output_name() -> str:
    return "custom_antenna"


__all__ = [
    "BuildAndSimulateRequest",
    "BuildAndSimulateResult",
    "LeamService",
    "OptimizationRequest",
    "OptimizationResult",
    "OptimizationValidationResult",
    "ParameterUpdateRequest",
    "ParameterUpdateResult",
    "ProjectContextSnapshot",
    "apply_parameter_updates",
    "build_and_simulate",
    "get_project_context_snapshot",
    "list_templates",
    "optimize_parameters",
    "validate_optimization_request",
]
