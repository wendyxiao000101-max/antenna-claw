"""Tests for the optimizer goal template catalog."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from leam.services import GOAL_TEMPLATES, build_goal_plan  # noqa: E402


def test_goal_templates_whitelist_is_fixed():
    assert GOAL_TEMPLATES == (
        "s11_min_at_frequency",
        "bandwidth_max_in_band",
        "resonance_align_to_frequency",
    )


def test_unknown_template_raises():
    with pytest.raises(ValueError):
        build_goal_plan("make_it_awesome", {"frequency_ghz": 2.4})


def test_s11_min_at_frequency_single_point():
    plan = build_goal_plan(
        "s11_min_at_frequency",
        {"frequency_ghz": 2.4, "threshold_db": -10},
    )
    assert plan.template == "s11_min_at_frequency"
    assert plan.args["frequency_ghz"] == 2.4
    assert plan.args["threshold_db"] == -10.0
    assert "SinglePoint" in plan.vba_snippet
    assert '.SetGoalRange "2.4", "2.4"' in plan.vba_snippet
    assert '.SetGoalTarget "-10"' in plan.vba_snippet


def test_bandwidth_max_in_band_rejects_inverted_range():
    with pytest.raises(ValueError):
        build_goal_plan(
            "bandwidth_max_in_band",
            {"freq_start_ghz": 2.5, "freq_stop_ghz": 2.4},
        )


def test_bandwidth_max_in_band_emits_range_goal():
    plan = build_goal_plan(
        "bandwidth_max_in_band",
        {"freq_start_ghz": 2.4, "freq_stop_ghz": 2.5, "threshold_db": -6},
    )
    assert plan.template == "bandwidth_max_in_band"
    assert '.SetGoalRangeType "Range"' in plan.vba_snippet
    assert '.SetGoalRange "2.4", "2.5"' in plan.vba_snippet
    assert '.SetGoalTarget "-6"' in plan.vba_snippet


def test_resonance_align_to_frequency_uses_tolerance_band():
    plan = build_goal_plan(
        "resonance_align_to_frequency",
        {"frequency_ghz": 2.45, "tolerance_mhz": 50},
    )
    assert plan.template == "resonance_align_to_frequency"
    assert '.SetGoalOperator "min"' in plan.vba_snippet
    assert '.SetGoalRangeType "Range"' in plan.vba_snippet
    # ±50 MHz around 2.45 GHz → 2.40 - 2.50 GHz
    assert '.SetGoalRange "2.4", "2.5"' in plan.vba_snippet


def test_resonance_align_to_frequency_rejects_zero_tolerance():
    with pytest.raises(ValueError):
        build_goal_plan(
            "resonance_align_to_frequency",
            {"frequency_ghz": 2.4, "tolerance_mhz": 0},
        )


def test_missing_required_frequency_argument_raises():
    with pytest.raises(ValueError):
        build_goal_plan("s11_min_at_frequency", {"threshold_db": -10})
