"""Tests for OptimizationValidationService."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from leam.services import OptimizationValidationService  # noqa: E402


PARAMS_BAS = (
    "Dim names(1 To 3) As String\n"
    "Dim values(1 To 3) As String\n"
    "\n"
    'names(1) = "L"\n'
    'values(1) = "20"\n'
    'names(2) = "W"\n'
    'values(2) = "10"\n'
    'names(3) = "H"\n'
    'values(3) = "2"\n'
    "\n"
    "StoreParameters names, values\n"
)


@pytest.fixture
def params_bas(tmp_path: Path) -> Path:
    path = tmp_path / "demo_parameters.bas"
    path.write_text(PARAMS_BAS, encoding="utf-8")
    return path


def _base_request(**overrides):
    base = {
        "output_name": "demo",
        "variables": [{"name": "L", "min": 10, "max": 30}],
        "goals": [
            {"template": "s11_min_at_frequency", "args": {"frequency_ghz": 2.4}}
        ],
    }
    base.update(overrides)
    return base


def test_rejects_non_object_request():
    svc = OptimizationValidationService()
    report = svc.validate("not a dict")
    assert report["is_valid"] is False
    assert any(e["code"] == "REQUEST_NOT_OBJECT" for e in report["errors"])


def test_rejects_empty_output_name():
    svc = OptimizationValidationService()
    report = svc.validate({"output_name": ""})
    codes = {e["code"] for e in report["errors"]}
    assert "OUTPUT_NAME_REQUIRED" in codes
    assert "VARIABLES_REQUIRED" in codes
    assert "GOALS_REQUIRED" in codes


def test_variable_name_must_exist_in_parameter_list(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(variables=[{"name": "ghost", "min": 1, "max": 2}]),
        parameters_bas=params_bas,
    )
    assert report["is_valid"] is False
    codes = {e["code"] for e in report["errors"]}
    assert "VAR_NAME_UNKNOWN" in codes


def test_variable_range_inversion_is_rejected(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(variables=[{"name": "L", "min": 30, "max": 10}]),
        parameters_bas=params_bas,
    )
    codes = {e["code"] for e in report["errors"]}
    assert "VAR_RANGE_INVERTED" in codes


def test_init_out_of_range_is_warning_not_error(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(
            variables=[{"name": "L", "min": 10, "max": 30, "init": 99}]
        ),
        parameters_bas=params_bas,
    )
    assert report["is_valid"] is True
    warn_codes = {w["code"] for w in report["warnings"]}
    assert "VAR_INIT_OUT_OF_RANGE" in warn_codes


def test_duplicate_variable_name_is_rejected(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(
            variables=[
                {"name": "L", "min": 10, "max": 20},
                {"name": "L", "min": 5, "max": 30},
            ]
        ),
        parameters_bas=params_bas,
    )
    codes = {e["code"] for e in report["errors"]}
    assert "VAR_NAME_DUPLICATE" in codes


def test_numeric_string_values_are_coerced(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(
            variables=[{"name": "L", "min": "10mm", "max": "30 mm"}]
        ),
        parameters_bas=params_bas,
    )
    assert report["is_valid"] is True
    var = report["normalized"]["variables"][0]
    assert var["min"] == 10.0
    assert var["max"] == 30.0


def test_unknown_goal_template_is_rejected(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(
            goals=[{"template": "efficiency_max", "args": {}}]
        ),
        parameters_bas=params_bas,
    )
    codes = {e["code"] for e in report["errors"]}
    assert "GOAL_TEMPLATE_UNKNOWN" in codes


def test_missing_required_goal_arg_is_rejected(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(goals=[{"template": "s11_min_at_frequency", "args": {}}]),
        parameters_bas=params_bas,
    )
    codes = {e["code"] for e in report["errors"]}
    assert "GOAL_ARG_REQUIRED" in codes


def test_mhz_alias_is_normalized_to_ghz(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(
            goals=[
                {
                    "template": "s11_min_at_frequency",
                    "args": {"frequency_mhz": 2400, "threshold_db": -10},
                }
            ]
        ),
        parameters_bas=params_bas,
    )
    assert report["is_valid"] is True, report["errors"]
    goal = report["normalized"]["goals"][0]
    assert goal["args"]["frequency_ghz"] == pytest.approx(2.4)


def test_bandwidth_range_inversion_is_rejected(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(
            goals=[
                {
                    "template": "bandwidth_max_in_band",
                    "args": {"freq_start_ghz": 2.5, "freq_stop_ghz": 2.4},
                }
            ]
        ),
        parameters_bas=params_bas,
    )
    codes = {e["code"] for e in report["errors"]}
    assert "GOAL_RANGE_INVERTED" in codes


def test_positive_threshold_db_is_warning(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(
            goals=[
                {
                    "template": "s11_min_at_frequency",
                    "args": {"frequency_ghz": 2.4, "threshold_db": 5},
                }
            ]
        ),
        parameters_bas=params_bas,
    )
    assert report["is_valid"] is True
    codes = {w["code"] for w in report["warnings"]}
    assert "GOAL_THRESHOLD_SIGN" in codes


def test_unknown_algorithm_falls_back_with_warning(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(algorithm="simulated-annealing"),
        parameters_bas=params_bas,
    )
    assert report["is_valid"] is True
    assert report["normalized"]["algorithm"] == "Trust Region Framework"
    codes = {w["code"] for w in report["warnings"]}
    assert "ALGORITHM_UNKNOWN" in codes


def test_max_evaluations_out_of_bounds_is_clamped(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(max_evaluations=5000),
        parameters_bas=params_bas,
    )
    assert report["is_valid"] is True
    assert report["normalized"]["max_evaluations"] == 500
    codes = {w["code"] for w in report["warnings"]}
    assert "MAX_EVAL_TOO_HIGH" in codes


def test_max_evaluations_non_integer_is_rejected(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(max_evaluations="many"),
        parameters_bas=params_bas,
    )
    codes = {e["code"] for e in report["errors"]}
    assert "MAX_EVAL_INVALID" in codes


def test_well_formed_request_validates(params_bas):
    svc = OptimizationValidationService()
    report = svc.validate(
        _base_request(
            variables=[
                {"name": "L", "min": 10, "max": 30, "init": 20},
                {"name": "W", "min": 5, "max": 15},
            ],
            goals=[
                {
                    "template": "bandwidth_max_in_band",
                    "args": {
                        "freq_start_ghz": 2.4,
                        "freq_stop_ghz": 2.5,
                        "threshold_db": -10,
                    },
                }
            ],
            algorithm="Nelder Mead Simplex",
            max_evaluations=60,
        ),
        parameters_bas=params_bas,
    )
    assert report["is_valid"] is True
    normalized = report["normalized"]
    assert normalized["algorithm"] == "Nelder Mead Simplex"
    assert normalized["max_evaluations"] == 60
    assert normalized["variables"][0]["init"] == 20.0
    assert normalized["goals"][0]["args"]["freq_start_ghz"] == pytest.approx(2.4)
