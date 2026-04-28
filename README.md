# LEAM

![LEAM Logo](assets/brand/leam-logo.png)

[中文文档](README.zh-CN.md)

LEAM (LLM-Enabled Antenna Modeling) is a headless Python backend for OpenClaw. It turns structured antenna-design requests into deterministic CST Studio Suite artifacts: model files, simulation exports, optimizer runs, and parameter-update records.

OpenClaw owns the conversation, intent routing, user confirmation, S-parameter analysis, plotting, and design decisions. LEAM owns repeatable execution.

## What LEAM Provides

Stable imports are exposed from `leam`:

```python
from pathlib import Path

from leam import (
    BuildAndSimulateRequest,
    OptimizationRequest,
    ParameterUpdateRequest,
    build_and_simulate,
    get_project_context_snapshot,
    list_templates,
    optimize_parameters,
    validate_optimization_request,
    apply_parameter_updates,
)
```

Main capabilities:

- Template/new/rerun antenna model generation.
- CST project creation, simulation, and S11 CSV export.
- CST Optimizer integration with validation and result diagnostics.
- Deterministic post-simulation parameter edits.
- File-system contracts for OpenClaw under `examples/output/<output_name>/`.

Built-in template coverage currently includes an air-substrate PIFA template under `src/leam/templates/air_pifa`.

## Installation

```powershell
cd antenna-claw
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

For CST Studio Suite 2023, use a Python version supported by CST's Python libraries. In practice, Python 3.9 is the safe target for CST-backed runs.

Package data includes:

- `prompts/*.md`
- `resources/*.md`
- `templates/*/TEMPLATE.md`
- `templates/*/data/*.json`

## Configuration

Create a local `config.json` or set LEAM-specific environment variables.

Example `config.json`:

```json
{
  "cst_path": "C:\\Program Files\\CST Studio Suite 2023",
  "openai_api_key": "YOUR_API_KEY"
}
```

Environment variables:

- `CST_PATH`: CST Studio Suite install root.
- `LEAM_OPENAI_API_KEY`: OpenAI key used only by LEAM.
- `LEAM_ALLOW_GLOBAL_OPENAI_API_KEY=1`: opt in to reading generic `OPENAI_API_KEY`.

By default, LEAM does not read generic `OPENAI_API_KEY`. This prevents a host process such as OpenClaw or Codex from accidentally routing unrelated OpenAI SDK calls through the user's paid LEAM key.

Check the environment:

```powershell
leam doctor
```

`doctor` checks:

- LEAM OpenAI key availability.
- CST install path.
- CST material library path.
- CST Python library path.

## Core Workflow

### Build And Simulate

```python
result = build_and_simulate(
    BuildAndSimulateRequest(
        description="2.45 GHz air substrate PIFA antenna",
        output_name="pifa_demo",
        execution_mode="simulate_and_export",
        simulation_request="2.0-3.0GHz Open Add Space 50 Ohm",
        run_cst=True,
        prefer_template=True,
    ),
    project_root=Path.cwd(),
)
```

Execution modes:

- `build_only`: generate JSON/BAS artifacts only.
- `simulate_and_export`: build CST project, run solver, export S11.
- `simulate_only`: rerun an existing output directory.

### Optimization

Optimization is intentionally a two-step flow:

1. Call `validate_optimization_request`.
2. Show the normalized variables/goals/budget to the user and get confirmation.
3. Call `optimize_parameters`.

```python
req = OptimizationRequest(
    output_name="pifa_demo",
    variables=[
        {"name": "Lp", "min": 17.2, "max": 18.4},
        {"name": "sPins", "min": 0.8, "max": 1.8},
    ],
    goals=[
        {
            "template": "resonance_align_to_frequency",
            "args": {
                "frequency_ghz": 2.45,
                "target_db": -30,
                "tolerance_mhz": 50,
            },
        }
    ],
    algorithm="Nelder Mead Simplex",
    max_evaluations=20,
)

validation = validate_optimization_request(
    req,
    project_root=Path.cwd(),
)

if validation.is_valid:
    # OpenClaw must show validation.normalized["optimizer_budget"] to the user
    # and receive confirmation before running CST.
    result = optimize_parameters(
        req,
        project_root=Path.cwd(),
    )
```

Supported algorithms:

- `Trust Region Framework`
- `Nelder Mead Simplex`
- `Interpolated Quasi Newton`
- `Classic Powell`
- `Genetic Algorithm`
- `Particle Swarm Optimization`

Supported goal templates:

- `s11_min_at_frequency`
- `bandwidth_max_in_band`
- `resonance_align_to_frequency`

### Optimizer Budget Semantics

`max_evaluations` always means the user's total solver-run budget.

For local optimizers such as Nelder Mead and Trust Region, LEAM maps this directly to CST `SetMaxEval`.

For population optimizers (`Particle Swarm Optimization` and `Genetic Algorithm`), CST uses iterations and population size. LEAM therefore computes an `optimizer_budget` during validation:

```json
{
  "requested_max_evaluations": 36,
  "algorithm_family": "population",
  "cst_limit_type": "iterations",
  "max_iterations": 4,
  "population_size": 8,
  "estimated_solver_runs": 32,
  "budget_policy": "strict_total_solver_runs",
  "requires_user_confirmation": true,
  "population_size_control": "SetGenerationSize"
}
```

Default population size is:

```text
min(12, max(4, 2 * variable_count + 2))
```

If explicit `max_iterations * population_size` exceeds `max_evaluations`, validation fails. This prevents a request like "36 evaluations" from becoming hundreds or thousands of CST solver runs.

### Explicit Parameter Updates

Use this when OpenClaw wants to directly patch known generated parameters without regenerating the design:

```python
apply_parameter_updates(
    ParameterUpdateRequest(
        output_name="pifa_demo",
        updates={"Lp": 17.6, "sPins": 1.3},
        purpose="Retune resonance after S11 review",
    ),
    project_root=Path.cwd(),
)
```

LEAM only accepts existing ParameterList names.

## Output Contract

Each `output_name` maps to:

```text
examples/output/<output_name>/
|-- run.json
|-- <output_name>.json
|-- <output_name>_parameters.bas
|-- <output_name>_dimensions.json
|-- <output_name>_materials.bas
|-- <output_name>_model.bas
|-- <output_name>_boolean.bas
|-- <output_name>.cst
`-- results/
    |-- manifest.json
    |-- simulation_audit.json
    |-- sparams/
    |   |-- s11.csv
    |   `-- s11.s1p
    `-- optimization/
        |-- manifest.json
        |-- audit.json
        |-- best_parameters.json
        `-- history.csv
```

Notes:

- Treat `run.json` as the root record for an output directory.
- S11 export uses CSV as the reliable path for CST 2023.
- Touchstone export may degrade to CSV when CST's `TOUCHSTONE.Write` fails.
- Optimizer status and solver diagnostics live in `results/optimization/manifest.json`.

## CST Integration Notes

LEAM uses CST's `Optimizer` object, not the older `Optimizer1D` API.

Important behaviors:

- Optimizer configuration and start are executed with inline VBA, not added as visible History steps.
- S11 CSV export reads directly from CST `ResultTree`; it does not depend on the currently selected plot view or `ASCIIExport`.
- LEAM parses CST optimizer result files such as `Result/Model.opt` and `Result/Model_ui.opt`.
- Solver errors, zero new solver evaluations, and failed best-parameter readback are reported as failed optimization states rather than silent success.

## Development

```powershell
cd antenna-claw
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
pytest tests -q
```

Build a wheel:

```powershell
python -m pip wheel . -w dist
```

Local runtime artifacts are ignored by git:

- `config.json`
- `.env`
- virtual environments
- `dist/`, `build/`
- `examples/output/**`

## Removed Legacy Interfaces

This package is now a headless backend. Do not use removed interactive paths such as:

- `leam.app`
- `leam.agent.*`
- old SQLite session-store modules
- interactive CLI/chat loops
- `input()`-based confirmations

OpenClaw is responsible for conversation and confirmation. LEAM is responsible for deterministic execution.

## License

MIT. See [LICENSE](LICENSE).
