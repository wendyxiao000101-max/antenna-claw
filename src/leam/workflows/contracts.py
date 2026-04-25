"""Frozen CLI behavior contracts.

This module centralizes the user-visible contracts that must remain stable
across refactors (workflow modes, output naming, key prompts and file names).
"""

from dataclasses import dataclass
from typing import Dict, Tuple


WORKFLOW_MODES: Tuple[str, ...] = ("new", "rerun", "template")
DESIGN_MODES: Tuple[str, str] = ("weak", "strong")
EXECUTION_MODES: Tuple[str, str, str] = (
    "build_only",
    "simulate_and_export",
    "simulate_only",
)
WORKFLOW_EXECUTION_MODES: Dict[str, Tuple[str, ...]] = {
    "new": ("build_only",),
    "rerun": ("build_only", "simulate_only"),
    "template": ("build_only", "simulate_and_export"),
}


@dataclass(frozen=True)
class OutputContract:
    """Naming contract for generated files."""

    json: str
    parameters: str
    dimensions: str
    materials: str
    model: str
    boolean: str
    cst: str

    @staticmethod
    def from_output_name(output_name: str) -> "OutputContract":
        return OutputContract(
            json=f"{output_name}.json",
            parameters=f"{output_name}_parameters.bas",
            dimensions=f"{output_name}_dimensions.json",
            materials=f"{output_name}_materials.bas",
            model=f"{output_name}_model.bas",
            boolean=f"{output_name}_boolean.bas",
            cst=f"{output_name}.cst",
        )

