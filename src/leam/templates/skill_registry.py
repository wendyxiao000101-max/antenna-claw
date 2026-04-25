"""Template skill registry with progressive disclosure and candidate promotion."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import SessionPaths
from ..services.parameter_service import ParameterService
from .template_runner import TemplateRunner


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TemplateSkillRegistry:
    """Read template metadata and create candidate template packages."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.runner = TemplateRunner()

    def list_briefs(self) -> List[Dict[str, Any]]:
        briefs: List[Dict[str, Any]] = []
        for meta in self.runner.list_templates():
            briefs.append(
                {
                    "template_id": meta.template_id,
                    "name": meta.name,
                    "antenna_type": meta.antenna_type,
                    "substrate": meta.substrate,
                    "baseline_frequency_ghz": meta.baseline_frequency_ghz,
                    "keywords": list(meta.match_keywords),
                    "editable_params": list(meta.editable_params),
                }
            )
        return briefs

    def load_detail(self, template_id: str) -> Optional[Dict[str, Any]]:
        for template in self.runner.discover_templates():
            meta = template.metadata
            if meta.template_id != template_id:
                continue
            md_path = template.template_dir / "TEMPLATE.md"
            md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
            return {
                "metadata": {
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
                    "entry_class": meta.entry_class,
                    "entry_module": meta.entry_module,
                },
                "template_dir": str(template.template_dir),
                "template_md_excerpt": md_text[:2500],
            }
        return None

    def recommend(self, description: str, top_k: int = 3) -> List[Dict[str, Any]]:
        text = (description or "").lower()
        ranked: List[Dict[str, Any]] = []
        for brief in self.list_briefs():
            score = 0
            for kw in brief.get("keywords", []):
                if kw.lower() in text:
                    score += 2
            if brief.get("antenna_type", "").lower() in text:
                score += 1
            if brief.get("substrate", "").lower() in text:
                score += 1
            if score > 0:
                ranked.append({**brief, "score": score})

        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[: max(1, int(top_k))]

    def promote_candidate(
        self,
        *,
        session_paths: SessionPaths,
        description: str,
        feedback: str,
        candidate_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        candidate_dir = session_paths.output_dir / "template_candidate"
        replay_dir = candidate_dir / "replay"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        replay_dir.mkdir(parents=True, exist_ok=True)

        required_files = {
            "solids_json": session_paths.json,
            "parameters_bas": session_paths.parameters,
            "dimensions_json": session_paths.dimensions,
            "materials_bas": session_paths.materials,
            "model_bas": session_paths.model,
            "boolean_bas": session_paths.boolean,
        }

        checks = []
        for kind, path in required_files.items():
            checks.append(
                {
                    "kind": kind,
                    "path": str(path),
                    "exists": path.exists(),
                    "size_bytes": path.stat().st_size if path.exists() else 0,
                }
            )

        complete = all(item["exists"] for item in checks)
        params = []
        if session_paths.parameters.exists():
            params = ParameterService.parse_bas(
                session_paths.parameters.read_text(encoding="utf-8")
            )

        candidate = {
            "candidate_id": self._candidate_id(session_paths.output_dir.name),
            "candidate_name": candidate_name or f"{session_paths.output_dir.name}_candidate",
            "created_at_utc": _utc_now(),
            "source_output_name": session_paths.output_dir.name,
            "description": description,
            "feedback": feedback,
            "status": "pending_review",
            "required_files_complete": complete,
            "files": checks,
            "baseline_parameters": params,
            "history_references": [str(path) for path in required_files.values() if path.exists()],
            "review_gate": {
                "type": "manual_confirmation_required",
                "rules": [
                    "required files must exist",
                    "parameter table must be parseable",
                    "candidate must include replay artifacts",
                ],
            },
        }

        candidate_path = candidate_dir / "template_candidate.json"
        report_path = candidate_dir / "validation_report.json"

        candidate_path.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        report = {
            "created_at_utc": _utc_now(),
            "is_valid": complete and len(params) > 0,
            "checks": checks,
            "parameter_count": len(params),
            "errors": self._validation_errors(complete, params),
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        copied_files: List[str] = []
        for path in required_files.values():
            if not path.exists():
                continue
            dst = replay_dir / path.name
            shutil.copy2(path, dst)
            copied_files.append(str(dst))

        return {
            "candidate_path": str(candidate_path),
            "report_path": str(report_path),
            "replay_files": copied_files,
            "is_valid": bool(report["is_valid"]),
        }

    @staticmethod
    def _validation_errors(complete: bool, params: List[Dict[str, Any]]) -> List[str]:
        errors: List[str] = []
        if not complete:
            errors.append("required output files are incomplete")
        if not params:
            errors.append("failed to parse baseline parameters from *_parameters.bas")
        return errors

    @staticmethod
    def _candidate_id(base_name: str) -> str:
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in base_name)
        return f"{cleaned}_cand_{now}"
