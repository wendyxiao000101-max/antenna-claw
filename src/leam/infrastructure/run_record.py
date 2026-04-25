"""Filesystem-only run manifest for OpenClaw state reconstruction.

This replaces the old SQLite-backed session store. Every LEAM run writes
a single ``run.json`` at the root of its output directory describing:

- which workflow executed (``template`` / ``new`` / ``rerun``)
- the execution mode and whether CST was invoked
- the full set of generated artifacts with existence flags
- the best-known simulation status (read back from
  ``results/manifest.json`` when present)

OpenClaw reads this file to restore state across sessions without LEAM
owning any persistent database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..models import SessionPaths

RUN_RECORD_FILENAME = "run.json"
SCHEMA_VERSION = "1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_entry(path: Path) -> Dict[str, Any]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
    }


def _read_json_safely(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_run_record(
    *,
    paths: SessionPaths,
    workflow: str,
    output_name: str,
    execution_mode: str,
    run_cst: bool,
    description: str = "",
    template_id: Optional[str] = None,
    matched_template: bool = False,
    simulation_request: str = "",
) -> Path:
    """Write ``<output_dir>/run.json`` and return the file path.

    The record is deterministic given (paths, workflow, execution_mode,
    run_cst, template_id): two identical runs produce identical content
    save for the timestamp.
    """
    simulation_manifest = _read_json_safely(paths.manifest)
    simulation_audit = _read_json_safely(paths.simulation_audit)

    record: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "workflow": workflow,
        "output_name": output_name,
        "execution_mode": execution_mode,
        "run_cst": bool(run_cst),
        "description": description or "",
        "template": {
            "matched": bool(matched_template),
            "template_id": template_id,
        },
        "simulation_request": simulation_request or "",
        "artifacts": {
            "output_dir": str(paths.output_dir),
            "solids_json": _path_entry(paths.json),
            "parameters_bas": _path_entry(paths.parameters),
            "dimensions_json": _path_entry(paths.dimensions),
            "materials_bas": _path_entry(paths.materials),
            "model_bas": _path_entry(paths.model),
            "boolean_bas": _path_entry(paths.boolean),
            "cst_project": _path_entry(paths.cst),
        },
        "results": {
            "manifest": _path_entry(paths.manifest),
            "simulation_audit": _path_entry(paths.simulation_audit),
            "s11_touchstone": _path_entry(paths.s11_touchstone),
            "s11_csv": _path_entry(paths.s11_csv),
        },
        "optimization": {
            "manifest": _path_entry(paths.optimization_manifest),
            "audit": _path_entry(paths.optimization_audit),
            "best_parameters": _path_entry(paths.best_parameters),
            "history_csv": _path_entry(paths.optimization_history_csv),
        },
        "simulation_status": (
            simulation_manifest.get("status")
            if isinstance(simulation_manifest, dict)
            else None
        ),
        "simulation_manifest_excerpt": _excerpt(simulation_manifest),
        "simulation_audit_excerpt": _excerpt(simulation_audit),
        "optimization_status": _read_optimization_status(paths),
    }

    record_path = paths.output_dir / RUN_RECORD_FILENAME
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return record_path


def read_run_record(output_dir: Path) -> Optional[Dict[str, Any]]:
    """Load the ``run.json`` from ``output_dir`` or return ``None``."""
    return _read_json_safely(Path(output_dir) / RUN_RECORD_FILENAME)


def _read_optimization_status(paths: SessionPaths) -> Optional[str]:
    payload = _read_json_safely(paths.optimization_manifest)
    if isinstance(payload, dict):
        return payload.get("status")
    return None


def _excerpt(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a compact subset of a manifest/audit for the run record.

    Keeps the run record small while still letting OpenClaw decide
    whether to open the full files.
    """
    if not isinstance(payload, dict):
        return None
    keys = (
        "status",
        "timestamp_utc",
        "frequency_ghz",
        "result_file",
        "result_format",
        "degraded_export",
        "error",
        "source_project",
    )
    return {k: payload[k] for k in keys if k in payload}
