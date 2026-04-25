"""Tests for topology-check toggle in new workflow."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _build_stub_workflow():
    from leam.workflows.new_design_workflow import NewDesignWorkflow

    workflow = object.__new__(NewDesignWorkflow)

    calls = {"topology": 0}

    class _Gen:
        @staticmethod
        def generate_solids(session):
            return None

        @staticmethod
        def generate_parameters(session):
            return None

        @staticmethod
        def generate_dimensions(session):
            return None

        @staticmethod
        def generate_materials(session):
            return None

        @staticmethod
        def generate_model_and_boolean(session):
            return None

    class _Topo:
        @staticmethod
        def run(session, callback):
            calls["topology"] += 1

    workflow.generation_service = _Gen()
    workflow.topology_workflow = _Topo()
    workflow.warn_if_existing_outputs = lambda session: None
    workflow._run_consistency_or_raise = lambda session: None
    workflow._print_generated_files = lambda session: None
    workflow._run_cst = lambda session: None
    workflow._run_with_mode = lambda session, execution_mode, simulation_request: None
    return workflow, calls


def test_run_skips_topology_when_disabled():
    workflow, calls = _build_stub_workflow()
    session = SimpleNamespace(paths=SimpleNamespace(), description="demo")
    workflow.run(
        session,
        run_cst=False,
        execution_mode="build_only",
        simulation_request="",
        enable_topology_check=False,
    )
    assert calls["topology"] == 0


def test_run_runs_topology_by_default():
    workflow, calls = _build_stub_workflow()
    session = SimpleNamespace(paths=SimpleNamespace(), description="demo")
    workflow.run(
        session,
        run_cst=False,
        execution_mode="build_only",
        simulation_request="",
    )
    assert calls["topology"] == 1
