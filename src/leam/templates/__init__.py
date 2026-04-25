"""Pluggable antenna-template framework.

Each template lives in its own sub-directory and is automatically
discovered by :class:`TemplateRunner` via a ``TEMPLATE.md`` file.
"""

from .base_template import (
    BaseTemplate,
    MatchResult,
    TemplateMetadata,
    ValidationResult,
)
from .template_runner import TemplateRunner

__all__ = [
    "BaseTemplate",
    "MatchResult",
    "TemplateMetadata",
    "TemplateRunner",
    "ValidationResult",
]
