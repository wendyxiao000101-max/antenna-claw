"""One-shot helper to regenerate the expected_output/ reference files.

Run from the repository root:
    py src/leam/templates/air_pifa/examples/generate_expected.py
"""

import json
import sys
from pathlib import Path

# Ensure the src directory is on the import path
_repo = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_repo / "src"))

from leam.templates.air_pifa.scripts.pifa_base import load_baseline  # noqa: E402
from leam.templates.air_pifa.scripts.pifa_generator import generate_all  # noqa: E402

out_dir = Path(__file__).resolve().parent / "expected_output"

baseline = load_baseline()
files = generate_all(baseline, out_dir, "air_pifa_2p4g")
for f in files:
    print("OK:", f.name)
