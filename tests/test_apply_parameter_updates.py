"""Tests for explicit OpenClaw-driven parameter updates."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from leam.service_api import LeamService, ParameterUpdateRequest  # noqa: E402


def _seed_project(tmp_path: Path, name: str = "demo"):
    out_dir = tmp_path / "examples" / "output" / name
    out_dir.mkdir(parents=True, exist_ok=True)
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
    (out_dir / f"{name}.json").write_text(
        json.dumps({"parameters": {"L": 20, "W": 10}, "solids": []}),
        encoding="utf-8",
    )
    (out_dir / f"{name}_dimensions.json").write_text(
        json.dumps(
            {
                "unit": "mm",
                "parameters": {"L": 20, "W": 10},
                "solids": [{"dimensions": {"Xmax": "L/2"}}],
            }
        ),
        encoding="utf-8",
    )
    (out_dir / f"{name}_materials.bas").write_text("Sub Main\nEnd Sub\n", encoding="utf-8")
    (out_dir / f"{name}_model.bas").write_text(
        'With Brick\n.Xrange "-L/2", "L/2"\nEnd With\n',
        encoding="utf-8",
    )
    (out_dir / f"{name}_boolean.bas").write_text("Sub Main\nEnd Sub\n", encoding="utf-8")
    return out_dir


def test_apply_parameter_updates_patches_generated_artifacts(tmp_path):
    out_dir = _seed_project(tmp_path)
    svc = LeamService(project_root=tmp_path)

    result = svc.apply_parameter_updates(
        ParameterUpdateRequest(
            output_name="demo",
            updates={"L": "24mm"},
            purpose="lower resonance",
            natural_language="把 L 改成 24mm，让谐振频率降低",
        )
    )

    assert result.status == "success"
    assert result.changed_parameters == {"L": {"old": "20", "new": "24"}}
    assert set(result.updated_files) == {
        "parameters_bas",
        "solids_json",
        "dimensions_json",
    }

    params_bas = (out_dir / "demo_parameters.bas").read_text(encoding="utf-8")
    assert 'names(1) = "L"' in params_bas
    assert 'values(1) = "24"' in params_bas
    assert "StoreParameters names, values" in params_bas

    solids = json.loads((out_dir / "demo.json").read_text(encoding="utf-8"))
    dims = json.loads((out_dir / "demo_dimensions.json").read_text(encoding="utf-8"))
    assert solids["parameters"]["L"] == 24
    assert dims["parameters"]["L"] == 24

    assert result.audit_path is not None
    audit = json.loads(Path(result.audit_path).read_text(encoding="utf-8"))
    assert audit["purpose"] == "lower resonance"
    assert audit["changed_parameters"]["L"]["new"] == "24"

    assert result.run_record_path is not None
    run_record = json.loads(Path(result.run_record_path).read_text(encoding="utf-8"))
    assert run_record["last_parameter_update"]["audit_path"] == result.audit_path


def test_apply_parameter_updates_rejects_unknown_parameter(tmp_path):
    _seed_project(tmp_path)
    svc = LeamService(project_root=tmp_path)

    result = svc.apply_parameter_updates(
        ParameterUpdateRequest(output_name="demo", updates={"unknown": 12})
    )

    assert result.status == "failed"
    assert result.errors[0]["code"] == "PARAMETER_UNKNOWN"


def test_apply_parameter_updates_reports_no_change(tmp_path):
    _seed_project(tmp_path)
    svc = LeamService(project_root=tmp_path)

    result = svc.apply_parameter_updates(
        ParameterUpdateRequest(output_name="demo", updates={"L": "20"})
    )

    assert result.status == "success"
    assert result.changed_parameters == {}
    assert result.updated_files == {}
    assert result.warnings[0]["code"] == "NO_PARAMETER_VALUE_CHANGED"
