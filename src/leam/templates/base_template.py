"""Abstract base class that every antenna template must implement."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class TemplateMetadata:
    """Parsed from the YAML front-matter of TEMPLATE.md."""

    template_id: str
    name: str
    version: str
    antenna_type: str
    substrate: str
    baseline_frequency_ghz: float
    entry_class: str
    entry_module: str
    match_keywords: List[str] = field(default_factory=list)
    match_substrate: List[str] = field(default_factory=list)
    editable_params: List[str] = field(default_factory=list)
    locked_params: List[str] = field(default_factory=list)


@dataclass
class MatchResult:
    """Returned by ``BaseTemplate.match`` on a successful hit."""

    target_frequency_ghz: float
    extra: Dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class BaseTemplate(ABC):
    """Interface that every template plug-in directory must expose."""

    def __init__(self, template_dir: Path, metadata: TemplateMetadata):
        self.template_dir = template_dir
        self.metadata = metadata

    # ------------------------------------------------------------------
    @abstractmethod
    def match(self, description: str) -> Optional[MatchResult]:
        """Return a MatchResult if *description* fits this template, else None."""

    @abstractmethod
    def build_params(self, match_result: MatchResult) -> dict:
        """Load baseline, scale / derive params from *match_result*."""

    @abstractmethod
    def validate(self, params: dict, target_ghz: float) -> ValidationResult:
        """Check physical constraints. Return errors / warnings."""

    def review_and_edit(self, params: dict, target_ghz: float) -> dict:
        """Non-interactive default: render a summary and return params unchanged.

        Subclasses may override to add headless post-processing (no
        ``input()`` calls). Interactive review used to live here but has
        been removed so LEAM can run as a backend service.
        """
        return params

    @abstractmethod
    def generate(
        self, params: dict, output_dir: Path, output_name: str
    ) -> List[Path]:
        """Write all output files deterministically. Return their paths."""
