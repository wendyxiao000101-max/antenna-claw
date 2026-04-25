"""Session models used by workflow orchestration."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from ..workflows.contracts import OutputContract


@dataclass(frozen=True)
class SessionPaths:
    """Resolved filesystem paths for one run."""

    output_dir: Path
    contract: OutputContract

    @property
    def json(self) -> Path:
        return self.output_dir / self.contract.json

    @property
    def parameters(self) -> Path:
        return self.output_dir / self.contract.parameters

    @property
    def dimensions(self) -> Path:
        return self.output_dir / self.contract.dimensions

    @property
    def materials(self) -> Path:
        return self.output_dir / self.contract.materials

    @property
    def model(self) -> Path:
        return self.output_dir / self.contract.model

    @property
    def boolean(self) -> Path:
        return self.output_dir / self.contract.boolean

    @property
    def cst(self) -> Path:
        return self.output_dir / self.contract.cst

    @property
    def results_dir(self) -> Path:
        return self.output_dir / "results"

    @property
    def sparams_dir(self) -> Path:
        return self.results_dir / "sparams"

    @property
    def s11_touchstone(self) -> Path:
        return self.sparams_dir / "s11.s1p"

    @property
    def s11_csv(self) -> Path:
        return self.sparams_dir / "s11.csv"

    @property
    def manifest(self) -> Path:
        return self.results_dir / "manifest.json"

    @property
    def simulation_audit(self) -> Path:
        return self.results_dir / "simulation_audit.json"

    # ----- Optimization artifacts (CST optimizer path) -----
    @property
    def optimization_dir(self) -> Path:
        return self.results_dir / "optimization"

    @property
    def optimization_manifest(self) -> Path:
        return self.optimization_dir / "manifest.json"

    @property
    def optimization_audit(self) -> Path:
        return self.optimization_dir / "audit.json"

    @property
    def best_parameters(self) -> Path:
        return self.optimization_dir / "best_parameters.json"

    @property
    def optimization_history_csv(self) -> Path:
        return self.optimization_dir / "history.csv"

    @property
    def required_rerun_files(self) -> List[Path]:
        return [
            self.json,
            self.dimensions,
            self.parameters,
            self.materials,
            self.model,
            self.boolean,
        ]

    @staticmethod
    def build(output_dir: Path, output_name: str) -> "SessionPaths":
        return SessionPaths(
            output_dir=output_dir,
            contract=OutputContract.from_output_name(output_name),
        )


@dataclass
class DesignSession:
    """Mutable state shared across a design workflow.

    Only carries fields that are read by the workflow or persisted to
    disk. Chat-era bookkeeping (``pipeline_mode``, ``topology_messages``,
    ``last_geometry_plan``) was removed when LEAM became a stateless
    backend service; OpenClaw owns session state now.
    """

    output_name: str
    mode: str
    description: str
    paths: SessionPaths
    run_cst: bool = False
    consistency_errors: List[str] = field(default_factory=list)

