"""Tests for the OpenClaw-facing LEAM service facade."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from leam.service_api import (  # noqa: E402
    BuildAndSimulateRequest,
    LeamService,
    OptimizationRequest,
)


def _svc(tmp_path: Path) -> LeamService:
    return LeamService(project_root=tmp_path)


def test_request_requires_description_or_base_name(tmp_path):
    svc = _svc(tmp_path)
    with pytest.raises(ValueError):
        svc.build_and_simulate(BuildAndSimulateRequest())


def test_request_rejects_description_and_base_name_together(tmp_path):
    svc = _svc(tmp_path)
    with pytest.raises(ValueError):
        svc.build_and_simulate(
            BuildAndSimulateRequest(description="pifa 2.4G", base_name="demo")
        )


def test_request_rejects_unknown_execution_mode(tmp_path):
    svc = _svc(tmp_path)
    with pytest.raises(ValueError):
        svc.build_and_simulate(
            BuildAndSimulateRequest(description="demo", execution_mode="bogus")
        )


def test_request_rejects_unknown_design_mode(tmp_path):
    svc = _svc(tmp_path)
    with pytest.raises(ValueError):
        svc.build_and_simulate(
            BuildAndSimulateRequest(description="demo", design_mode="bogus")
        )


def test_dispatches_to_rerun_and_captures_paths(tmp_path, monkeypatch):
    svc = _svc(tmp_path)

    calls = {}

    class _FakeRerun:
        def __init__(self, project_root):
            calls["project_root"] = project_root

        def run(self, base_name, *, run_cst, execution_mode, simulation_request):
            calls["rerun"] = {
                "base_name": base_name,
                "run_cst": run_cst,
                "execution_mode": execution_mode,
                "simulation_request": simulation_request,
            }

    monkeypatch.setattr("leam.service_api.RerunWorkflow", _FakeRerun)

    result = svc.build_and_simulate(
        BuildAndSimulateRequest(
            base_name="demo_existing",
            execution_mode="simulate_only",
            simulation_request="2.4-2.5GHz S11",
            run_cst=True,
        )
    )

    assert calls["rerun"]["base_name"] == "demo_existing"
    assert calls["rerun"]["execution_mode"] == "simulate_only"
    assert result.workflow == "rerun"
    assert result.output_name == "demo_existing"
    assert result.output_dir.endswith("demo_existing")
    assert result.run_record_path is not None
    assert Path(result.run_record_path).exists()


def test_dispatches_to_template_when_match(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    template_calls = {}

    class _FakeTemplate:
        def __init__(self, project_root):
            template_calls["project_root"] = project_root

        def run(self, **kwargs):
            template_calls["kwargs"] = kwargs
            return {"matched": True, "template_id": "fake_template", "files": []}

    class _FakeRerun:
        def __init__(self, project_root):
            pass

        def run(self, *args, **kwargs):  # pragma: no cover — should not be called here
            raise AssertionError("RerunWorkflow must not be invoked for a template hit")

    monkeypatch.setattr("leam.service_api.TemplateWorkflow", _FakeTemplate)
    monkeypatch.setattr("leam.service_api.RerunWorkflow", _FakeRerun)
    monkeypatch.setattr(
        LeamService,
        "_try_template_match",
        lambda self, description: ("fake_template_obj", "fake_match_result"),
    )

    result = svc.build_and_simulate(
        BuildAndSimulateRequest(
            description="设计 2.4 GHz 空气介质 PIFA",
            output_name="pifa_24g",
            execution_mode="simulate_and_export",
            simulation_request="2.4-2.5GHz Open Add Space",
            run_cst=True,
        )
    )

    assert result.workflow == "template"
    assert result.matched_template is True
    assert result.template_id == "fake_template"
    assert template_calls["kwargs"]["skip_review"] is True
    assert template_calls["kwargs"]["execution_mode"] == "simulate_and_export"


def test_dispatches_to_new_then_rerun_when_no_template(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    calls = {"new": None, "rerun": None}

    class _FakeNew:
        def __init__(self, project_root):
            pass

        def build_session(self, **kwargs):
            calls["session"] = kwargs

            class _S:
                pass

            return _S()

        def run(self, session, **kwargs):
            calls["new"] = kwargs

    class _FakeRerun:
        def __init__(self, project_root):
            pass

        def run(self, base_name, *, run_cst, execution_mode, simulation_request):
            calls["rerun"] = {
                "base_name": base_name,
                "run_cst": run_cst,
                "execution_mode": execution_mode,
                "simulation_request": simulation_request,
            }

    monkeypatch.setattr("leam.service_api.NewDesignWorkflow", _FakeNew)
    monkeypatch.setattr("leam.service_api.RerunWorkflow", _FakeRerun)
    monkeypatch.setattr(LeamService, "_try_template_match", lambda self, d: None)

    result = svc.build_and_simulate(
        BuildAndSimulateRequest(
            description="自定义的偶极子天线",
            output_name="custom_dipole",
            execution_mode="simulate_and_export",
            simulation_request="2.4-2.5GHz",
            run_cst=True,
        )
    )

    assert result.workflow == "new"
    assert calls["new"]["execution_mode"] == "build_only"
    assert calls["rerun"] is not None
    assert calls["rerun"]["execution_mode"] == "simulate_only"


def test_build_only_skips_rerun_chain(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    calls = {"rerun_called": False}

    class _FakeNew:
        def __init__(self, project_root):
            pass

        def build_session(self, **kwargs):
            class _S:
                pass

            return _S()

        def run(self, session, **kwargs):
            pass

    class _FakeRerun:
        def __init__(self, project_root):
            pass

        def run(self, *args, **kwargs):
            calls["rerun_called"] = True

    monkeypatch.setattr("leam.service_api.NewDesignWorkflow", _FakeNew)
    monkeypatch.setattr("leam.service_api.RerunWorkflow", _FakeRerun)
    monkeypatch.setattr(LeamService, "_try_template_match", lambda self, d: None)

    svc.build_and_simulate(
        BuildAndSimulateRequest(
            description="test", output_name="t", execution_mode="build_only"
        )
    )

    assert calls["rerun_called"] is False


def test_list_templates_returns_registered_templates(tmp_path):
    svc = _svc(tmp_path)
    templates = svc.list_templates()
    assert any(t["template_id"] == "air_pifa" for t in templates)


def test_validate_optimization_request_returns_structured_errors(tmp_path):
    svc = _svc(tmp_path)
    req = OptimizationRequest(output_name="demo")
    result = svc.validate_optimization_request(req)
    assert result.is_valid is False
    codes = {e["code"] for e in result.errors}
    assert "VARIABLES_REQUIRED" in codes
    assert "GOALS_REQUIRED" in codes
    assert "PROJECT_MISSING" in codes
