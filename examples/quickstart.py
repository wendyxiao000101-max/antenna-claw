"""Minimal OpenClaw-facing walkthrough for the LEAM service API.

Run from the repository root:

    python examples/quickstart.py

This script does NOT invoke CST by default (``run_cst=False``) so it is
safe to execute on any machine for a smoke test. Set ``RUN_CST=True`` at
the top of ``main()`` once CST is configured to see the full pipeline.
"""

import sys
from pathlib import Path
from pprint import pprint

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from leam import (
    BuildAndSimulateRequest,
    LeamService,
    OptimizationRequest,
)


def main() -> None:
    RUN_CST = False
    service = LeamService(project_root=PROJECT_ROOT)

    templates = service.list_templates()
    print(f"Found {len(templates)} template(s):")
    for t in templates:
        print(f"  - {t['template_id']} ({t['antenna_type']}, {t['baseline_frequency_ghz']} GHz)")

    print("\n--- build_and_simulate (template path) ---")
    build_result = service.build_and_simulate(
        BuildAndSimulateRequest(
            description="2.4 GHz 空气介质 PIFA 天线",
            output_name="pifa_quickstart",
            execution_mode="build_only" if not RUN_CST else "simulate_and_export",
            simulation_request="2.4-2.5GHz Open Add Space 50 Ohm",
            run_cst=RUN_CST,
            prefer_template=True,
        )
    )
    pprint(build_result.to_dict())

    print("\n--- get_project_context_snapshot ---")
    snapshot = service.get_project_context_snapshot("pifa_quickstart")
    print(f"exists={snapshot.exists} has_cst={snapshot.has_cst_project} "
          f"has_params={snapshot.has_parameters_bas}")
    print("Parameters:")
    for p in snapshot.parameters:
        print(f"  {p['name']}={p['value']} # {p['comment']}")
    print("Last simulation:", snapshot.last_simulation or "(none yet)")
    print("Goal templates:", [g["template"] for g in snapshot.goal_templates])

    print("\n--- validate_optimization_request (dry-run) ---")
    candidate_params = [p["name"] for p in snapshot.parameters]
    if not candidate_params:
        print("(no parameters yet; skipping optimization preview)")
        return

    variable_name = candidate_params[0]
    req = OptimizationRequest(
        output_name="pifa_quickstart",
        variables=[{"name": variable_name, "min": 10.0, "max": 40.0}],
        goals=[
            {
                "template": "s11_min_at_frequency",
                "args": {"frequency_ghz": 2.45, "threshold_db": -10},
            }
        ],
        algorithm="Trust Region Framework",
        max_evaluations=20,
        natural_language=f"先扫一下 {variable_name} 看看谐振点走势",
    )
    check = service.validate_optimization_request(req)
    print(f"is_valid={check.is_valid}")
    if check.errors:
        print("Errors:")
        for err in check.errors:
            print(f"  [{err['code']}] {err['field']}: {err['message']}")
    if check.warnings:
        print("Warnings:")
        for warn in check.warnings:
            print(f"  [{warn['code']}] {warn['field']}: {warn['message']}")

    if RUN_CST and check.is_valid:
        print("\n--- optimize_parameters (CST) ---")
        opt_result = service.optimize_parameters(req)
        pprint(opt_result.to_dict())


if __name__ == "__main__":
    main()
