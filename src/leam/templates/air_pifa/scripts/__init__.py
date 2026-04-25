"""Air-substrate PIFA template — entry point for the template framework."""

import re
from pathlib import Path
from typing import Dict, List, Optional

from leam.templates.base_template import (
    BaseTemplate,
    MatchResult,
    TemplateMetadata,
    ValidationResult,
)

from .pifa_base import baseline_frequency, estimate_resonance, load_baseline, scale_for_frequency
from .pifa_generator import generate_all
from .pifa_review import render_header, review_summary
from .pifa_validator import validate


class AirPifaTemplate(BaseTemplate):
    """Concrete template for the air-substrate PIFA antenna."""

    _FREQ_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[Gg][Hh][Zz]")
    _FREQ_RANGE_RE = re.compile(
        r"(\d+(?:\.\d+)?)\s*[\-\u2013~\u5230]\s*(\d+(?:\.\d+)?)\s*[Gg][Hh][Zz]"
    )
    # Competing substrate keywords: presence of any of these *without* an
    # air/空气 mention indicates the user wants a different dielectric,
    # so the air-PIFA template should abstain.
    _COMPETING_SUBSTRATES = (
        "fr4", "rogers", "ro3003", "ro4003", "ro4350",
        "\u9676\u74f7",  # 陶瓷
        "\u4ecb\u8d28\u57fa\u677f", "\u4ecb\u8d28\u677f",  # 介质基板/介质板
    )

    def match(self, description: str) -> Optional[MatchResult]:
        desc_lower = description.lower()

        keyword_hit = any(kw.lower() in desc_lower for kw in self.metadata.match_keywords)
        if not keyword_hit:
            return None

        wanted_subs = [s.lower() for s in (self.metadata.match_substrate or [])]
        substrate_hit = any(s in desc_lower for s in wanted_subs) if wanted_subs else True
        if not substrate_hit and any(c in desc_lower for c in self._COMPETING_SUBSTRATES):
            # User explicitly asked for a competing substrate: abstain.
            return None

        range_match = self._FREQ_RANGE_RE.search(description)
        if range_match:
            lo, hi = float(range_match.group(1)), float(range_match.group(2))
            target_ghz = round((lo + hi) / 2.0, 3)
        else:
            freq_match = self._FREQ_RE.search(description)
            target_ghz = (
                float(freq_match.group(1))
                if freq_match
                else self.metadata.baseline_frequency_ghz
            )

        return MatchResult(target_frequency_ghz=target_ghz)

    def build_params(self, match_result: MatchResult) -> Dict:
        baseline = load_baseline()
        f_base = baseline_frequency()

        if abs(match_result.target_frequency_ghz - f_base) / f_base < 0.01:
            return baseline

        return scale_for_frequency(match_result.target_frequency_ghz, baseline)

    def validate(self, params: Dict, target_ghz: float) -> ValidationResult:
        return validate(params, target_ghz)

    def review_and_edit(self, params: Dict, target_ghz: float) -> Dict:
        f_base = baseline_frequency()
        if abs(target_ghz - f_base) / f_base < 0.01:
            strategy = "直接使用优化后 baseline（频率匹配）"
        else:
            strategy = f"基于 {f_base} GHz baseline 按频率反比缩放"
        render_header(self.metadata, target_ghz, strategy)
        return review_summary(params, target_ghz, self.metadata)

    def generate(
        self, params: Dict, output_dir: Path, output_name: str
    ) -> List[Path]:
        return generate_all(params, output_dir, output_name)
