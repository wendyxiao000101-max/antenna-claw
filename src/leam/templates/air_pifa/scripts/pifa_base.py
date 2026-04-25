"""Baseline loading and frequency-scaling logic for the air-substrate PIFA."""

import json
from pathlib import Path
from typing import Dict

SPEED_OF_LIGHT_MM_S = 299_792_458_000.0  # mm/s


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def load_baseline() -> Dict:
    """Return the optimized geometry dict from *optimized_pifa_params.json*."""
    path = _data_dir() / "optimized_pifa_params.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return dict(raw["geometry"])


def baseline_frequency() -> float:
    path = _data_dir() / "optimized_pifa_params.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return float(raw["target_frequency_ghz"])


def estimate_resonance(params: Dict) -> float:
    """Estimate resonance frequency (GHz) using the PIFA quarter-wave formula.

    f = c / (4 * (Lp + Wp - Ws))
    where Ws approximates the shorting-pin effective width (= dPin here).
    """
    lp = params["Lp"]
    wp = params["Wp"]
    ws = params["dPin"]
    effective_length = lp + wp - ws
    if effective_length <= 0:
        return 0.0
    freq_hz = SPEED_OF_LIGHT_MM_S / (4.0 * effective_length)
    return freq_hz / 1e9


def scale_for_frequency(target_ghz: float, baseline: Dict) -> Dict:
    """Return a new param dict scaled from *baseline* toward *target_ghz*.

    Scaling rules (from PIFA theory):
      - Lp, Wp: inversely proportional to frequency
      - sPins:   scales with Wp ratio (matching-sensitive)
      - Lg, Wg:  scale with ratio, clamped to >= 2*Lp / 2*Wp
      - h, t_cu, dPin, gPort: unchanged (process / bandwidth params)
    """
    f_base = baseline_frequency()
    ratio = f_base / target_ghz

    params = dict(baseline)

    params["Lp"] = baseline["Lp"] * ratio
    params["Wp"] = baseline["Wp"] * ratio
    params["sPins"] = baseline["sPins"] * ratio

    params["Lg"] = max(baseline["Lg"] * ratio, 2.0 * params["Lp"])
    params["Wg"] = max(baseline["Wg"] * ratio, 2.0 * params["Wp"])

    return params
