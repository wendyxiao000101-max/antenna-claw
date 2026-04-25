"""Generic discovery and execution engine for antenna templates.

Scans ``src/leam/templates/`` for sub-directories that contain a
``TEMPLATE.md`` with a YAML front-matter block, dynamically imports
the declared entry class, and exposes helpers for matching user
descriptions and running the full template pipeline.
"""

import importlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base_template import BaseTemplate, MatchResult, TemplateMetadata


def _parse_yaml_frontmatter(text: str) -> Dict:
    """Minimal YAML front-matter parser (no external dependency).

    Handles scalars, simple lists (``- item``), and quoted strings.
    """
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}

    data: Dict = {}
    current_key: Optional[str] = None
    current_list: Optional[list] = None

    for line in m.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            if current_list is not None:
                val = stripped[2:].strip().strip('"').strip("'")
                current_list.append(val)
            continue

        kv = re.match(r'^(\w+)\s*:\s*(.*)', stripped)
        if kv:
            if current_key and current_list is not None:
                data[current_key] = current_list

            current_key = kv.group(1)
            raw_val = kv.group(2).strip().strip('"').strip("'")
            if raw_val == "":
                current_list = []
            else:
                current_list = None
                data[current_key] = raw_val
        else:
            current_list = None

    if current_key and current_list is not None:
        data[current_key] = current_list

    return data


def _strip_frontmatter(text: str) -> str:
    """Return the markdown body with the leading ``--- ... ---`` block removed."""
    m = re.match(r"^---\s*\n.*?\n---\s*\n?", text, re.DOTALL)
    if m:
        return text[m.end():].strip()
    return text.strip()


def _metadata_from_dict(d: Dict) -> TemplateMetadata:
    def _list(key: str) -> List[str]:
        v = d.get(key, [])
        return v if isinstance(v, list) else [v]

    return TemplateMetadata(
        template_id=d.get("template_id", ""),
        name=d.get("name", ""),
        version=str(d.get("version", "0.0")),
        antenna_type=d.get("antenna_type", ""),
        substrate=d.get("substrate", ""),
        baseline_frequency_ghz=float(d.get("baseline_frequency_ghz", 0)),
        entry_class=d.get("entry_class", ""),
        entry_module=d.get("entry_module", "scripts"),
        match_keywords=_list("match_keywords"),
        match_substrate=_list("match_substrate"),
        editable_params=_list("editable_params"),
        locked_params=_list("locked_params"),
    )


class TemplateRunner:
    """Discover, match, and execute antenna templates.

    LEAM no longer keeps an internal match cache or interactive
    low-confidence confirmation hook; OpenClaw owns caching and
    disambiguation. ``match()`` now always returns the top rule hit or
    the top LLM suggestion, or ``None`` if nothing is found.
    """

    def __init__(self, *, use_llm_fallback: bool = True) -> None:
        self._templates: Optional[List[BaseTemplate]] = None
        self._doc_bodies: Dict[str, str] = {}
        self._use_llm_fallback = use_llm_fallback
        self._llm_matcher = None  # lazy

    @property
    def templates_root(self) -> Path:
        return Path(__file__).resolve().parent

    def discover_templates(self) -> List[BaseTemplate]:
        if self._templates is not None:
            return self._templates

        found: List[BaseTemplate] = []
        bodies: Dict[str, str] = {}
        for child in sorted(self.templates_root.iterdir()):
            if not child.is_dir():
                continue
            md_path = child / "TEMPLATE.md"
            if not md_path.exists():
                continue
            try:
                text = md_path.read_text(encoding="utf-8")
                meta = _metadata_from_dict(_parse_yaml_frontmatter(text))
                if not meta.template_id or not meta.entry_class:
                    continue
                mod = importlib.import_module(
                    f"leam.templates.{child.name}.{meta.entry_module}"
                )
                cls = getattr(mod, meta.entry_class)
                instance: BaseTemplate = cls(template_dir=child, metadata=meta)
                found.append(instance)
                bodies[meta.template_id] = _strip_frontmatter(text)
            except Exception as exc:  # noqa: BLE001
                print(f"  [模板发现] 跳过 {child.name}: {exc}")

        self._templates = found
        self._doc_bodies = bodies
        return found

    def match(
        self, description: str
    ) -> Optional[Tuple[BaseTemplate, MatchResult]]:
        templates = self.discover_templates()
        if not templates:
            return None

        for tmpl in templates:
            result = tmpl.match(description)
            if result is not None:
                return tmpl, result

        if not self._use_llm_fallback:
            return None
        return self._llm_match(description, templates)

    def _llm_match(
        self, description: str, templates: List[BaseTemplate]
    ) -> Optional[Tuple[BaseTemplate, MatchResult]]:
        """Fallback: ask an LLM to pick the best template from the catalog."""
        if self._llm_matcher is None:
            try:
                from ..services.template_matching_service import (
                    TemplateMatchingService,
                )

                self._llm_matcher = TemplateMatchingService()
            except Exception as exc:  # noqa: BLE001
                print(f"  [\u6a21\u677f\u5339\u914d] LLM \u5151\u5e95\u4e0d\u53ef\u7528: {exc}")
                return None

        ranked = self._llm_matcher.suggest(
            description,
            [t.metadata for t in templates],
            body_by_id=self._doc_bodies,
            top_k=3,
        )
        if not ranked:
            return None

        chosen = ranked[0]
        tmpl = next(
            (t for t in templates if t.metadata.template_id == chosen.template_id),
            None,
        )
        if tmpl is None:
            return None

        print(
            f"  [\u6a21\u677f\u5339\u914d] LLM \u9009\u4e2d: {tmpl.metadata.name} "
            f"(id={chosen.template_id}, conf={chosen.confidence:.2f}, "
            f"\u7406\u7531={chosen.reason})"
        )
        return tmpl, MatchResult(
            target_frequency_ghz=chosen.target_frequency_ghz,
            extra={
                "matched_by": "llm",
                "confidence": chosen.confidence,
                "reason": chosen.reason,
            },
        )

    def list_templates(self) -> List[TemplateMetadata]:
        return [t.metadata for t in self.discover_templates()]

    def run(
        self,
        template: BaseTemplate,
        match_result: MatchResult,
        output_dir: Path,
        output_name: str,
        *,
        skip_review: bool = False,
    ) -> List[Path]:
        params = template.build_params(match_result)
        vr = template.validate(params, match_result.target_frequency_ghz)
        if not vr.is_valid:
            print("\n参数校验失败：")
            for e in vr.errors:
                print(f"  - {e}")
            raise RuntimeError("模板参数校验未通过，已停止。")
        if not skip_review:
            params = template.review_and_edit(params, match_result.target_frequency_ghz)
        return template.generate(params, output_dir, output_name)
