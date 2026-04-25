"""Tests for the OpenClaw-facing optimize_parameters entry."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from leam.service_api import LeamService, OptimizationRequest  # noqa: E402


def _prepare_project(tmp_path: Path, name: str = "demo") -> Path:
    """Seed a minimal output directory as if build_and_simulate already ran."""
    project_root = tmp_path
    out_dir = project_root / "examples" / "output" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.cst").write_text("", encoding="utf-8")
    params_bas = (
        "Dim names(1 To 2) As String\n"
        "Dim values(1 To 2) As String\n"
        "\n"
        'names(1) = "L"\n'
        'values(1) = "20"\n'
        'names(2) = "W"\n'
        'values(2) = "10"\n'
        "\n"
        "StoreParameters names, values\n"
    )
    (out_dir / f"{name}_parameters.bas").write_text(params_bas, encoding="utf-8")
    return project_root


def test_rejects_empty_request_fields(tmp_path):
    svc = LeamService(project_root=tmp_path)

    result_empty_name = svc.optimize_parameters(OptimizationRequest(output_name=""))
    assert result_empty_name.status == "failed"
    assert result_empty_name.error == "validation_failed"

    _prepare_project(tmp_path)
    result_no_vars = svc.optimize_parameters(OptimizationRequest(output_name="demo"))
    assert result_no_vars.status == "failed"
    assert result_no_vars.error == "validation_failed"

    result_no_goals = svc.optimize_parameters(
        OptimizationRequest(
            output_name="demo",
            variables=[{"name": "L", "min": 10, "max": 30}],
        )
    )
    assert result_no_goals.status == "failed"
    assert result_no_goals.error == "validation_failed"


def test_returns_failure_when_cst_project_missing(tmp_path):
    svc = LeamService(project_root=tmp_path)
    result = svc.optimize_parameters(
        OptimizationRequest(
            output_name="missing",
            variables=[{"name": "L", "min": 10, "max": 30}],
            goals=[{"template": "s11_min_at_frequency", "args": {"frequency_ghz": 2.4}}],
        )
    )
    assert result.status == "failed"
    assert result.error == "validation_failed"

    validation = svc.validate_optimization_request(
        OptimizationRequest(
            output_name="missing",
            variables=[{"name": "L", "min": 10, "max": 30}],
            goals=[{"template": "s11_min_at_frequency", "args": {"frequency_ghz": 2.4}}],
        )
    )
    assert validation.is_valid is False
    codes = {e["code"] for e in validation.errors}
    assert "PROJECT_MISSING" in codes


def test_optimize_parameters_dispatches_to_gateway(tmp_path, monkeypatch):
    _prepare_project(tmp_path)

    calls = {}

    class _FakeGateway:
        def run_optimization(
            self,
            *,
            paths,
            variables,
            goals,
            algorithm,
            max_evaluations,
            use_current_as_init,
            nl_request,
            parsed_request,
        ):
            calls["paths"] = paths
            calls["variables"] = variables
            calls["goals"] = goals
            calls["algorithm"] = algorithm
            calls["max_evaluations"] = max_evaluations
            paths.optimization_dir.mkdir(parents=True, exist_ok=True)
            paths.optimization_manifest.write_text(
                json.dumps(
                    {
                        "status": "success",
                        "algorithm": algorithm,
                        "best_parameters": {"L": "21.3", "W": "9.8"},
                    }
                ),
                encoding="utf-8",
            )
            paths.best_parameters.write_text(
                json.dumps(
                    {
                        "parameters": {"L": "21.3", "W": "9.8"},
                        "seeds": {"L": "20", "W": "10"},
                        "variables": variables,
                        "algorithm": algorithm,
                    }
                ),
                encoding="utf-8",
            )
            paths.optimization_audit.write_text(
                json.dumps({"algorithm": algorithm}), encoding="utf-8"
            )
            return {
                "status": "success",
                "algorithm": algorithm,
                "best_parameters": {"L": "21.3", "W": "9.8"},
            }

    monkeypatch.setattr("leam.service_api.CstGateway", lambda: _FakeGateway())

    svc = LeamService(project_root=tmp_path)
    result = svc.optimize_parameters(
        OptimizationRequest(
            output_name="demo",
            variables=[
                {"name": "L", "min": 10.0, "max": 30.0, "init": 20.0},
                {"name": "W", "min": 5.0, "max": 15.0},
            ],
            goals=[
                {
                    "template": "s11_min_at_frequency",
                    "args": {"frequency_ghz": 2.4, "threshold_db": -10},
                },
            ],
            algorithm="Trust Region Framework",
            max_evaluations=20,
            natural_language="现在谐振频率太高了，帮我把 L 压到 10-30 mm 之间",
        )
    )

    assert result.status == "success"
    assert result.best_parameters == {"L": "21.3", "W": "9.8"}
    assert result.optimization_manifest_path is not None
    assert result.best_parameters_path is not None
    assert calls["algorithm"] == "Trust Region Framework"
    assert len(calls["goals"]) == 1
    assert calls["goals"][0].template == "s11_min_at_frequency"
    assert calls["max_evaluations"] == 20


def test_optimize_parameters_reports_failure_without_raising(tmp_path, monkeypatch):
    _prepare_project(tmp_path)

    class _FailingGateway:
        def run_optimization(self, **kwargs):
            raise RuntimeError("CST refused the optimizer call")

    monkeypatch.setattr("leam.service_api.CstGateway", lambda: _FailingGateway())

    svc = LeamService(project_root=tmp_path)
    result = svc.optimize_parameters(
        OptimizationRequest(
            output_name="demo",
            variables=[{"name": "L", "min": 10, "max": 20}],
            goals=[{"template": "s11_min_at_frequency", "args": {"frequency_ghz": 2.4}}],
        )
    )

    assert result.status == "failed"
    assert "refused the optimizer call" in (result.error or "")
    assert result.best_parameters == {}


def test_validate_optimization_request_passes_for_well_formed_input(tmp_path):
    _prepare_project(tmp_path)
    svc = LeamService(project_root=tmp_path)
    result = svc.validate_optimization_request(
        OptimizationRequest(
            output_name="demo",
            variables=[{"name": "L", "min": 10, "max": 20}],
            goals=[{"template": "s11_min_at_frequency", "args": {"frequency_ghz": 2.4}}],
        )
    )
    assert result.is_valid is True
    assert result.errors == []
    assert result.normalized is not None
    assert result.normalized["algorithm"] == "Trust Region Framework"
    assert result.normalized["variables"][0]["name"] == "L"
