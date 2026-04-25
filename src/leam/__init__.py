"""LEAM: LLM-Enabled Antenna Modeling — OpenClaw-facing backend service."""

from .core.llm_caller import LLMCaller
from .core.vba_generator import VBAGenerator
from .service_api import (
    BuildAndSimulateRequest,
    BuildAndSimulateResult,
    LeamService,
    OptimizationRequest,
    OptimizationResult,
    OptimizationValidationResult,
    ParameterUpdateRequest,
    ParameterUpdateResult,
    ProjectContextSnapshot,
    apply_parameter_updates,
    build_and_simulate,
    get_project_context_snapshot,
    list_templates,
    optimize_parameters,
    validate_optimization_request,
)

__all__ = [
    "BuildAndSimulateRequest",
    "BuildAndSimulateResult",
    "LLMCaller",
    "LeamService",
    "OptimizationRequest",
    "OptimizationResult",
    "OptimizationValidationResult",
    "ParameterUpdateRequest",
    "ParameterUpdateResult",
    "ProjectContextSnapshot",
    "VBAGenerator",
    "apply_parameter_updates",
    "build_and_simulate",
    "get_project_context_snapshot",
    "list_templates",
    "optimize_parameters",
    "validate_optimization_request",
]
