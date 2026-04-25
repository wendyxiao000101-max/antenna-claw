"""Filesystem access for workflow outputs."""

import re
from pathlib import Path
from typing import List

from ..models import SessionPaths


class OutputRepository:
    """Centralized output directory and file naming operations."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.output_dir = self.project_root / "examples" / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_paths(self, output_name: str) -> SessionPaths:
        session_name = self._sanitize_session_name(output_name)
        session_dir = self.output_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        return SessionPaths.build(session_dir, output_name)

    @staticmethod
    def _sanitize_session_name(output_name: str) -> str:
        cleaned = output_name.strip()
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", cleaned)
        cleaned = cleaned.rstrip(". ")
        return cleaned or "custom_antenna"

    def existing_outputs(self, paths: SessionPaths) -> List[Path]:
        candidates = [
            paths.json,
            paths.parameters,
            paths.dimensions,
            paths.materials,
            paths.model,
            paths.boolean,
            paths.cst,
        ]
        return [p for p in candidates if p.exists()]

    def missing_required_for_rerun(self, paths: SessionPaths) -> List[Path]:
        return [p for p in paths.required_rerun_files if not p.exists()]

