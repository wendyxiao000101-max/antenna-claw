"""Lightweight workflows package exports.

Keep this module side-effect free to avoid import-time cycles:
- models.session -> workflows.contracts
- workflows.__init__ should NOT eagerly import heavy workflow modules
"""

from .contracts import (
    DESIGN_MODES,
    EXECUTION_MODES,
    WORKFLOW_MODES,
    OutputContract,
)

__all__ = [
    "WORKFLOW_MODES",
    "DESIGN_MODES",
    "EXECUTION_MODES",
    "OutputContract",
    "TemplateWorkflow",
]


def __getattr__(name: str):
    """Lazy compatibility export for heavy workflow classes."""
    if name == "TemplateWorkflow":
        from .template_workflow import TemplateWorkflow  # local import by design

        return TemplateWorkflow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
