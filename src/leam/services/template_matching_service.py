"""LLM-assisted template matching.

Given a user description and the list of registered templates, ask a
language model to pick the best-fitting template (if any) and extract
the target frequency. Used as a fallback when deterministic keyword
matching returns no hit — gives the chat mode much looser phrasing
tolerance without sacrificing the fast offline path.

Output contract (JSON, enforced by :func:`parse_json_maybe`)::

    {
      "suggestions": [
        {"template_id": "...", "target_frequency_ghz": 2.45,
         "confidence": 0.82, "reason": "..."},
        ...
      ],
      "note": "optional free-form remark"
    }

Back-compat: legacy single-object responses are accepted and coerced
into a one-item ``suggestions`` list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence

from ..templates.base_template import TemplateMetadata
from ..utils.json_utils import parse_json_maybe
from .llm_assist import quick_llm


@dataclass
class TemplateMatchSuggestion:
    template_id: str
    target_frequency_ghz: float
    confidence: float
    reason: str


class TemplateMatchingService:
    """Thin wrapper that renders a prompt and parses the LLM response."""

    MIN_CONFIDENCE = 0.5
    MAX_BODY_CHARS = 1200  # truncate long TEMPLATE.md bodies in the prompt

    _SYSTEM_PROMPT_TEMPLATE = (
        "You are a template-matching assistant for an antenna design tool.\n"
        "Given a user request and a catalog of antenna templates, rank the\n"
        "top candidates. Returning an empty list is allowed when nothing fits.\n"
        "Rules:\n"
        "- Only propose template_id values that appear in the catalog.\n"
        "- target_frequency_ghz is a number in GHz; for a range (e.g.\n"
        "  '2.4-2.5 GHz') return the center value.\n"
        "- confidence is in [0, 1]; be conservative when unsure.\n"
        "- Return at most 3 suggestions ordered by confidence desc.\n"
        "- When the user asks for a different substrate or antenna type\n"
        "  than any catalog entry supports, return an empty list.\n"
        "Return STRICTLY this JSON (no prose, no code fences):\n"
        "{\"suggestions\": ["
        "{\"template_id\": string, \"target_frequency_ghz\": number,"
        " \"confidence\": number, \"reason\": string}"
        "], \"note\": string}\n"
        "\n"
        "Template catalog:\n"
        "{catalog}"
    )

    def suggest(
        self,
        description: str,
        templates: Sequence[TemplateMetadata],
        *,
        body_by_id: Optional[Mapping[str, str]] = None,
        top_k: int = 3,
    ) -> List[TemplateMatchSuggestion]:
        description = (description or "").strip()
        if not description or not templates:
            return []

        catalog = self._render_catalog(templates, body_by_id or {})
        prompt = self._SYSTEM_PROMPT_TEMPLATE.replace("{catalog}", catalog)

        raw = quick_llm(prompt, description)
        parsed = parse_json_maybe(raw)
        entries = self._coerce_suggestions(parsed)
        if not entries:
            return []

        known_ids = {t.template_id for t in templates}
        meta_by_id = {t.template_id: t for t in templates}

        out: List[TemplateMatchSuggestion] = []
        seen: set[str] = set()
        for entry in entries:
            template_id = entry.get("template_id")
            if not isinstance(template_id, str) or template_id not in known_ids:
                continue
            if template_id in seen:
                continue
            try:
                confidence = float(entry.get("confidence", 0))
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence < self.MIN_CONFIDENCE:
                continue
            meta = meta_by_id[template_id]
            try:
                target_ghz = float(entry.get("target_frequency_ghz") or 0)
            except (TypeError, ValueError):
                target_ghz = 0.0
            if target_ghz <= 0:
                target_ghz = float(meta.baseline_frequency_ghz or 0)
            if target_ghz <= 0:
                continue
            seen.add(template_id)
            out.append(
                TemplateMatchSuggestion(
                    template_id=template_id,
                    target_frequency_ghz=target_ghz,
                    confidence=confidence,
                    reason=str(entry.get("reason", "")).strip(),
                )
            )
            if len(out) >= top_k:
                break
        return out

    def suggest_one(
        self,
        description: str,
        templates: Sequence[TemplateMetadata],
        *,
        body_by_id: Optional[Mapping[str, str]] = None,
    ) -> Optional[TemplateMatchSuggestion]:
        """Back-compat shim: return only the top suggestion (or None)."""
        ranked = self.suggest(description, templates, body_by_id=body_by_id, top_k=1)
        return ranked[0] if ranked else None

    @staticmethod
    def _coerce_suggestions(parsed) -> List[Dict]:
        if isinstance(parsed, dict):
            if isinstance(parsed.get("suggestions"), list):
                return [e for e in parsed["suggestions"] if isinstance(e, dict)]
            if parsed.get("template_id"):
                return [parsed]
            return []
        if isinstance(parsed, list):
            return [e for e in parsed if isinstance(e, dict)]
        return []

    def _render_catalog(
        self,
        templates: Sequence[TemplateMetadata],
        body_by_id: Mapping[str, str],
    ) -> str:
        entries: List[Dict] = []
        for meta in templates:
            body = (body_by_id.get(meta.template_id, "") or "").strip()
            if len(body) > self.MAX_BODY_CHARS:
                body = body[: self.MAX_BODY_CHARS] + "\n... [truncated]"
            entries.append(
                {
                    "template_id": meta.template_id,
                    "name": meta.name,
                    "antenna_type": meta.antenna_type,
                    "substrate": meta.substrate,
                    "baseline_frequency_ghz": meta.baseline_frequency_ghz,
                    "match_keywords": meta.match_keywords,
                    "match_substrate": meta.match_substrate,
                    "doc_excerpt": body,
                }
            )
        return json.dumps(entries, ensure_ascii=False, indent=2)
