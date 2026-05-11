# OpenClaw Paper Replication Workflow

This workflow lets OpenClaw reproduce an antenna paper with LEAM without adding
a new LEAM service API. OpenClaw reads the paper, extracts a structured
replication spec, then calls local helper scripts that translate the spec into
the existing `BuildAndSimulateRequest` flow.

## Responsibilities

OpenClaw owns:

- reading the PDF and figures;
- extracting topology, parameters, materials, feed/port, simulation setup, and
  S11 validation targets;
- showing missing fields and expensive CST actions to the user before running;
- reading LEAM artifacts and explaining whether the result matches the paper.

LEAM owns:

- `new` workflow geometry generation;
- CST project creation;
- CST simulation/export;
- file artifacts under `examples/output/<output_name>/`.

## PaperReplicationSpec

OpenClaw should write a JSON object with these top-level fields:

```json
{
  "output_name": "paper_antenna_name",
  "paper_meta": {
    "title": "Paper title",
    "year": 2026,
    "antenna_type": "Patch / PIFA / monopole / ...",
    "target_application": "Application band or system"
  },
  "topology": {
    "radiator": "Radiator shape and layers",
    "ground": "Ground plane and defects",
    "substrate": "Substrate stack",
    "feed": "Feed line/probe/CPW/coax description",
    "shorting_slits_slots_parasitics": "Relevant coupled structures",
    "coordinate_datum": "Origin and coordinate convention"
  },
  "parameters": [
    {
      "name": "L1",
      "value": 12.3,
      "unit": "mm",
      "source": "Table 1"
    }
  ],
  "materials": {
    "substrate": "FR4",
    "epsilon_r": 4.4,
    "loss_tangent": 0.02,
    "copper_thickness_mm": 0.035,
    "substrate_thickness_mm": 1.6
  },
  "port": {
    "type": "DiscretePort",
    "reference_impedance": 50,
    "feed_location": "Paper feed position",
    "positive_terminal": "Fed conductor",
    "negative_terminal": "Ground/reference conductor"
  },
  "simulation": {
    "frequency": {"start": 2.0, "stop": 3.0, "unit": "GHz"},
    "boundary": "Open Add Space",
    "solver": "auto",
    "export": "S11 touchstone"
  },
  "validation_targets": {
    "resonance_frequency_ghz": 2.45,
    "min_s11_db": -15,
    "minus_10db_band_ghz": {"start": 2.4, "stop": 2.5},
    "source": "Figure 6"
  }
}
```

Do not invent missing paper values silently. If a required topology, material,
port, or validation field cannot be extracted, OpenClaw should show the missing
field and ask the user before running CST.

## Commands

Build files first, without running CST:

```powershell
D:\leam_openclaw_handoff\.venv39\Scripts\python.exe D:\antenna-claw-source\openclaw_tools\paper_reproduce.py --spec <spec.json> --mode build-only --output-name <name>
```

After user confirmation, run CST simulation/export:

```powershell
D:\leam_openclaw_handoff\.venv39\Scripts\python.exe D:\antenna-claw-source\openclaw_tools\paper_reproduce.py --spec <spec.json> --mode simulate --output-name <name>
```

Compare S11 against paper targets:

```powershell
D:\leam_openclaw_handoff\.venv39\Scripts\python.exe D:\antenna-claw-source\openclaw_tools\compare_s11_to_paper.py --spec <spec.json> --output-name <name>
```

The comparison script writes:

- `examples/output/<output_name>/results/paper_reproduction_report.json`
- `examples/output/<output_name>/results/paper_reproduction_s11.png` when
  Pillow is installed.

If Pillow is not available, the JSON report is still produced.

## Behavior Notes

- Paper reproduction forces `prefer_template=False`, so LEAM uses the `new`
  workflow rather than a built-in template.
- First-pass agreement uses resonance frequency, minimum S11, and -10 dB
  bandwidth.
- A mismatch should be reported to the user. Do not start parameter tuning or
  optimization without a separate confirmation.
- Keep API keys and local `config.json` out of Git.
