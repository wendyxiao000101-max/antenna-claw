"""Tests for the filesystem run record writer/reader."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from leam.infrastructure import (  # noqa: E402
    RUN_RECORD_FILENAME,
    OutputRepository,
    read_run_record,
    write_run_record,
)


def _paths(tmp_path: Path, name: str = "demo"):
    repo = OutputRepository(tmp_path)
    return repo.build_paths(name)


def test_write_run_record_creates_top_level_run_json(tmp_path):
    paths = _paths(tmp_path)
    record_path = write_run_record(
        paths=paths,
        workflow="new",
        output_name="demo",
        execution_mode="build_only",
        run_cst=False,
        description="2.4G 空气介质 PIFA",
    )
    assert record_path.name == RUN_RECORD_FILENAME
    assert record_path.parent == paths.output_dir
    assert record_path.exists()


def test_run_record_content_captures_workflow_metadata(tmp_path):
    paths = _paths(tmp_path)
    write_run_record(
        paths=paths,
        workflow="template",
        output_name="demo",
        execution_mode="simulate_and_export",
        run_cst=True,
        description="demo",
        template_id="air_pifa",
        matched_template=True,
        simulation_request="2.4-2.5GHz",
    )
    payload = json.loads((paths.output_dir / RUN_RECORD_FILENAME).read_text("utf-8"))
    assert payload["workflow"] == "template"
    assert payload["execution_mode"] == "simulate_and_export"
    assert payload["run_cst"] is True
    assert payload["template"] == {"matched": True, "template_id": "air_pifa"}
    assert payload["simulation_request"] == "2.4-2.5GHz"
    assert payload["schema_version"]
    assert "created_at_utc" in payload


def test_run_record_tracks_existing_artifacts(tmp_path):
    paths = _paths(tmp_path)
    paths.parameters.parent.mkdir(parents=True, exist_ok=True)
    paths.parameters.write_text("Sub Define1D\nEnd Sub\n", encoding="utf-8")
    paths.model.write_text("Sub Main\nEnd Sub\n", encoding="utf-8")

    write_run_record(
        paths=paths,
        workflow="new",
        output_name="demo",
        execution_mode="build_only",
        run_cst=False,
    )
    payload = json.loads((paths.output_dir / RUN_RECORD_FILENAME).read_text("utf-8"))
    artifacts = payload["artifacts"]
    assert artifacts["parameters_bas"]["exists"] is True
    assert artifacts["parameters_bas"]["size_bytes"] > 0
    assert artifacts["boolean_bas"]["exists"] is False
    assert artifacts["boolean_bas"]["size_bytes"] == 0


def test_run_record_excerpts_simulation_manifest(tmp_path):
    paths = _paths(tmp_path)
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text(
        json.dumps(
            {
                "status": "success",
                "timestamp_utc": "2026-04-23T00:00:00+00:00",
                "frequency_ghz": {"start": 2.0, "stop": 3.0},
                "result_file": str(paths.s11_touchstone),
                "result_format": "touchstone",
            }
        ),
        encoding="utf-8",
    )

    write_run_record(
        paths=paths,
        workflow="template",
        output_name="demo",
        execution_mode="simulate_and_export",
        run_cst=True,
    )
    payload = read_run_record(paths.output_dir)
    assert payload is not None
    assert payload["simulation_status"] == "success"
    assert payload["simulation_manifest_excerpt"]["result_format"] == "touchstone"


def test_read_run_record_returns_none_when_missing(tmp_path):
    assert read_run_record(tmp_path / "nope") is None
