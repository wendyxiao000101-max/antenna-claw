"""Tests for LeamService.get_project_context_snapshot."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from leam.infrastructure import RUN_RECORD_FILENAME  # noqa: E402
from leam.service_api import LeamService  # noqa: E402


def _seed_project(tmp_path: Path, name: str = "demo") -> Path:
    out_dir = tmp_path / "examples" / "output" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.cst").write_text("", encoding="utf-8")
    (out_dir / f"{name}_parameters.bas").write_text(
        "Dim names(1 To 2) As String\n"
        "Dim values(1 To 2) As String\n"
        "\n"
        'names(1) = "L"  \' patch length\n'
        'values(1) = "20"\n'
        'names(2) = "W"\n'
        'values(2) = "10"\n'
        "StoreParameters names, values\n",
        encoding="utf-8",
    )
    return out_dir


def test_snapshot_requires_output_name(tmp_path):
    svc = LeamService(project_root=tmp_path)
    with pytest.raises(ValueError):
        svc.get_project_context_snapshot("")


def test_snapshot_for_missing_project_marks_absent(tmp_path):
    svc = LeamService(project_root=tmp_path)
    snap = svc.get_project_context_snapshot("ghost")
    assert snap.exists is False
    assert snap.has_cst_project is False
    assert snap.has_parameters_bas is False
    assert snap.parameters == []
    assert "s11_min_at_frequency" in {g["template"] for g in snap.goal_templates}
    assert "Trust Region Framework" in snap.algorithms
    assert snap.units == {"length": "mm", "frequency": "GHz"}


def test_snapshot_lists_parameters_and_status(tmp_path):
    out_dir = _seed_project(tmp_path)
    record = {
        "schema_version": "1.0",
        "workflow": "rerun",
        "execution": {"simulation_request": "2.4-2.5GHz S11"},
        "simulation": {
            "status": "success",
            "frequency": {"start": 2.4, "stop": 2.5, "unit": "GHz"},
        },
        "artifacts": {
            "s11_touchstone": {"path": str(out_dir / "results" / "sparams" / "s11.s1p")},
        },
    }
    (out_dir / RUN_RECORD_FILENAME).write_text(json.dumps(record), encoding="utf-8")

    svc = LeamService(project_root=tmp_path)
    snap = svc.get_project_context_snapshot("demo")

    assert snap.exists is True
    assert snap.has_cst_project is True
    assert snap.has_parameters_bas is True
    names = [p["name"] for p in snap.parameters]
    assert names == ["L", "W"]
    assert snap.parameters[0]["value"] == "20"
    assert snap.parameters[0]["comment"] == "patch length"
    assert snap.last_simulation.get("status") == "success"
    assert snap.last_simulation.get("request") == "2.4-2.5GHz S11"
    freq = snap.last_simulation.get("frequency") or {}
    assert freq.get("start") == 2.4

    templates = {g["template"]: g for g in snap.goal_templates}
    assert "frequency_ghz" in templates["s11_min_at_frequency"]["required_args"]
    assert "threshold_db" in templates["s11_min_at_frequency"]["optional_args"]

    assert snap.schema_hint["max_evaluations"].startswith("integer")


def test_snapshot_survives_missing_run_record(tmp_path):
    _seed_project(tmp_path)
    svc = LeamService(project_root=tmp_path)
    snap = svc.get_project_context_snapshot("demo")
    assert snap.exists is True
    assert snap.last_simulation == {}
    assert snap.parameters[0]["name"] == "L"
