"""Non-interactive smoke tests for the air-substrate PIFA template module.

Run with:  python -m pytest tests/test_air_pifa_template.py -v
Or simply:  python tests/test_air_pifa_template.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_template_discovery():
    from leam.templates import TemplateRunner

    runner = TemplateRunner()
    templates = runner.discover_templates()
    assert len(templates) >= 1, "Should discover at least the air_pifa template"
    ids = [t.metadata.template_id for t in templates]
    assert "air_pifa" in ids
    print("[PASS] test_template_discovery")


def test_match_positive():
    from leam.templates import TemplateRunner

    runner = TemplateRunner()

    result = runner.match("设计一个 2.4GHz 空气介质 PIFA 天线")
    assert result is not None
    tmpl, mr = result
    assert tmpl.metadata.template_id == "air_pifa"
    assert abs(mr.target_frequency_ghz - 2.4) < 0.01

    result2 = runner.match("I need a 5.8GHz air PIFA antenna")
    assert result2 is not None
    _, mr2 = result2
    assert abs(mr2.target_frequency_ghz - 5.8) < 0.01
    print("[PASS] test_match_positive")


def test_match_negative():
    from leam.templates import TemplateRunner

    runner = TemplateRunner()
    assert runner.match("设计一个 Vivaldi 天线") is None
    assert runner.match("设计一个 FR4 微带贴片天线") is None
    print("[PASS] test_match_negative")


def test_baseline_loading():
    from leam.templates.air_pifa.scripts.pifa_base import load_baseline, baseline_frequency

    bl = load_baseline()
    assert abs(bl["Lp"] - 18.142361067158) < 1e-6
    assert abs(bl["h"] - 6.0) < 1e-6
    assert abs(baseline_frequency() - 2.4) < 1e-6
    print("[PASS] test_baseline_loading")


def test_frequency_scaling():
    from leam.templates.air_pifa.scripts.pifa_base import (
        load_baseline,
        scale_for_frequency,
        estimate_resonance,
    )

    bl = load_baseline()
    scaled = scale_for_frequency(5.0, bl)

    assert scaled["Lp"] < bl["Lp"], "Higher freq -> smaller Lp"
    assert scaled["Wp"] < bl["Wp"], "Higher freq -> smaller Wp"
    assert scaled["h"] == bl["h"], "h should not change"
    assert scaled["t_cu"] == bl["t_cu"], "t_cu should not change"
    assert scaled["dPin"] == bl["dPin"], "dPin should not change"
    assert scaled["gPort"] == bl["gPort"], "gPort should not change"
    assert scaled["Lg"] >= 2 * scaled["Lp"], "Lg >= 2*Lp constraint"
    assert scaled["Wg"] >= 2 * scaled["Wp"], "Wg >= 2*Wp constraint"

    f_est = estimate_resonance(scaled)
    deviation = abs(f_est - 5.0) / 5.0
    assert deviation < 0.15, f"Estimated {f_est} GHz too far from 5.0 GHz"
    print("[PASS] test_frequency_scaling")


def test_validation_pass():
    from leam.templates.air_pifa.scripts.pifa_base import load_baseline
    from leam.templates.air_pifa.scripts.pifa_validator import validate

    bl = load_baseline()
    vr = validate(bl, 2.4)
    assert vr.is_valid, f"Baseline should pass validation, got errors: {vr.errors}"
    print("[PASS] test_validation_pass")


def test_validation_fail():
    from leam.templates.air_pifa.scripts.pifa_validator import validate

    bad = {
        "t_cu": 0.035, "Lg": 10, "Wg": 10,
        "h": 100, "Lp": 18, "Wp": 12,
        "dPin": 1.0, "sPins": 0.5, "gPort": 200,
    }
    vr = validate(bad, 2.4)
    assert not vr.is_valid, "Bad params should fail"
    assert len(vr.errors) > 0
    print("[PASS] test_validation_fail")


def test_param_editability():
    from leam.templates.air_pifa.scripts.pifa_validator import is_param_editable
    from leam.templates.base_template import TemplateMetadata

    meta = TemplateMetadata(
        template_id="air_pifa", name="test", version="1.0",
        antenna_type="PIFA", substrate="air",
        baseline_frequency_ghz=2.4, entry_class="X", entry_module="scripts",
        editable_params=["Lp", "Wp", "h", "sPins", "Lg", "Wg"],
        locked_params=["t_cu", "dPin", "gPort"],
    )
    assert is_param_editable("Lp", meta)
    assert is_param_editable("sPins", meta)
    assert not is_param_editable("t_cu", meta)
    assert not is_param_editable("gPort", meta)
    print("[PASS] test_param_editability")


def test_file_generation():
    from leam.templates.air_pifa.scripts.pifa_base import load_baseline
    from leam.templates.air_pifa.scripts.pifa_generator import generate_all

    bl = load_baseline()
    with tempfile.TemporaryDirectory() as td:
        files = generate_all(bl, Path(td), "test_pifa")
        assert len(files) == 6

        names = {f.name for f in files}
        assert "test_pifa.json" in names
        assert "test_pifa_parameters.bas" in names
        assert "test_pifa_dimensions.json" in names
        assert "test_pifa_materials.bas" in names
        assert "test_pifa_model.bas" in names
        assert "test_pifa_boolean.bas" in names

        params_text = (Path(td) / "test_pifa_parameters.bas").read_text(encoding="utf-8")
        assert "StoreParameters" in params_text
        assert '"Lp"' in params_text

        model_text = (Path(td) / "test_pifa_model.bas").read_text(encoding="utf-8")
        assert "GroundPlane" in model_text
        assert "RadiatingPatch" in model_text
        assert "ShortingPin" in model_text

        bool_text = (Path(td) / "test_pifa_boolean.bas").read_text(encoding="utf-8")
        assert "DiscretePort" in bool_text
        assert "Impedance" in bool_text

        solids_json = json.loads((Path(td) / "test_pifa.json").read_text(encoding="utf-8"))
        assert solids_json["antenna_type"] == "PIFA"
        assert len(solids_json["solids"]) == 6

    print("[PASS] test_file_generation")


def test_full_pipeline():
    """Run the full non-interactive pipeline via TemplateRunner."""
    from leam.templates import TemplateRunner

    runner = TemplateRunner()
    result = runner.match("设计一个 2.4GHz 空气介质 PIFA 天线")
    assert result is not None
    tmpl, mr = result
    params = tmpl.build_params(mr)
    vr = tmpl.validate(params, mr.target_frequency_ghz)
    assert vr.is_valid

    with tempfile.TemporaryDirectory() as td:
        files = tmpl.generate(params, Path(td), "pipeline_test")
        assert len(files) == 6
        for f in files:
            assert f.exists()
            assert f.stat().st_size > 0

    print("[PASS] test_full_pipeline")


if __name__ == "__main__":
    test_template_discovery()
    test_match_positive()
    test_match_negative()
    test_baseline_loading()
    test_frequency_scaling()
    test_validation_pass()
    test_validation_fail()
    test_param_editability()
    test_file_generation()
    test_full_pipeline()
    print("\n=== All tests passed! ===")
