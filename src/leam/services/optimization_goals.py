"""Goal template catalog for the CST optimizer.

This is the *translation* layer that converts a goal spec shaped by
OpenClaw (``{template, args}``) into:

- a deterministic ``goal_id`` (per-template + args-hash),
- a CST-compatible goal representation (function + target + operator),
- a VBA snippet that configures CST's ``Optimizer`` with that goal.

The companion validation layer (arg ranges, required fields, unit
normalization) is added in the next refactor cut (``harden-optimizer-intent``).
Here we only accept well-formed, already-validated inputs and fail
loudly otherwise — that keeps LEAM's optimizer strictly non-interactive.

Whitelisted templates (initial set):

- ``s11_min_at_frequency``   — drive |S11| below a threshold at a frequency.
- ``bandwidth_max_in_band``  — maximize how wide |S11| stays below threshold.
- ``resonance_align_to_frequency`` — pull the minimum of |S11| toward a target.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


GOAL_TEMPLATES = (
    "s11_min_at_frequency",
    "bandwidth_max_in_band",
    "resonance_align_to_frequency",
)


@dataclass
class GoalPlan:
    """Fully realized optimization goal ready to be pushed to CST."""

    template: str
    args: Dict[str, Any]
    description: str
    vba_snippet: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template": self.template,
            "args": dict(self.args),
            "description": self.description,
        }


def build_goal_plan(template: str, args: Dict[str, Any]) -> GoalPlan:
    """Return a :class:`GoalPlan` for the given template + args.

    The function is strict: unknown templates raise ``ValueError``. Arg
    validation is intentionally lightweight here; the dedicated
    validation service (next cut) is where OpenClaw's natural-language
    output gets robustly vetted.
    """
    if template not in GOAL_TEMPLATES:
        allowed = ", ".join(GOAL_TEMPLATES)
        raise ValueError(
            f"Unknown goal template: {template!r}. Allowed: {allowed}"
        )

    if template == "s11_min_at_frequency":
        return _s11_min_at_frequency(args)
    if template == "bandwidth_max_in_band":
        return _bandwidth_max_in_band(args)
    if template == "resonance_align_to_frequency":
        return _resonance_align_to_frequency(args)

    raise ValueError(f"Goal template dispatcher missed: {template}")


# ---------------------------------------------------------------------------
# Individual template builders
# ---------------------------------------------------------------------------


def _s11_min_at_frequency(args: Dict[str, Any]) -> GoalPlan:
    freq_ghz = _require_float(args, "frequency_ghz")
    threshold_db = float(args.get("threshold_db", -10.0))
    weight = float(args.get("weight", 1.0))

    vba = _emit_goal_vba(
        function_type="S11,1",
        operator="<",
        target=threshold_db,
        freq_ghz=freq_ghz,
        weight=weight,
        comment=f"|S11| < {threshold_db} dB at {freq_ghz} GHz",
    )
    return GoalPlan(
        template="s11_min_at_frequency",
        args={"frequency_ghz": freq_ghz, "threshold_db": threshold_db, "weight": weight},
        description=(
            f"Push |S11| below {threshold_db:g} dB at {freq_ghz:g} GHz "
            f"(weight={weight:g})."
        ),
        vba_snippet=vba,
    )


def _bandwidth_max_in_band(args: Dict[str, Any]) -> GoalPlan:
    freq_start = _require_float(args, "freq_start_ghz")
    freq_stop = _require_float(args, "freq_stop_ghz")
    if freq_stop <= freq_start:
        raise ValueError(
            "bandwidth_max_in_band requires freq_stop_ghz > freq_start_ghz; "
            f"got start={freq_start}, stop={freq_stop}"
        )
    threshold_db = float(args.get("threshold_db", -10.0))
    weight = float(args.get("weight", 1.0))

    vba = _emit_goal_vba(
        function_type="S11,1",
        operator="<",
        target=threshold_db,
        freq_range=(freq_start, freq_stop),
        weight=weight,
        comment=(
            f"|S11| < {threshold_db} dB across "
            f"{_fmt_number(freq_start)}-{_fmt_number(freq_stop)} GHz"
        ),
    )
    return GoalPlan(
        template="bandwidth_max_in_band",
        args={
            "freq_start_ghz": freq_start,
            "freq_stop_ghz": freq_stop,
            "threshold_db": threshold_db,
            "weight": weight,
        },
        description=(
            f"Keep |S11| below {threshold_db:g} dB across the whole "
            f"{freq_start:g}-{freq_stop:g} GHz band (weight={weight:g})."
        ),
        vba_snippet=vba,
    )


def _resonance_align_to_frequency(args: Dict[str, Any]) -> GoalPlan:
    freq_ghz = _require_float(args, "frequency_ghz")
    tolerance_mhz = float(args.get("tolerance_mhz", 50.0))
    target_db = float(args.get("target_db", -30.0))
    weight = float(args.get("weight", 1.0))
    if tolerance_mhz <= 0:
        raise ValueError("tolerance_mhz must be positive")

    vba = _emit_goal_vba(
        function_type="S11,1",
        operator="<",
        target=target_db,
        freq_ghz=freq_ghz,
        weight=weight,
        comment=(
            f"Force |S11| below {target_db} dB at "
            f"{_fmt_number(freq_ghz)} GHz so resonance is pulled to the target "
            f"(requested tolerance +/-{_fmt_number(tolerance_mhz)} MHz)"
        ),
    )
    return GoalPlan(
        template="resonance_align_to_frequency",
        args={
            "frequency_ghz": freq_ghz,
            "tolerance_mhz": tolerance_mhz,
            "target_db": target_db,
            "weight": weight,
        },
        description=(
            f"Force resonance toward {freq_ghz:g} GHz by requiring "
            f"|S11| < {target_db:g} dB at the target frequency "
            f"(tolerance={tolerance_mhz:g} MHz, weight={weight:g})."
        ),
        vba_snippet=vba,
    )


# ---------------------------------------------------------------------------
# VBA emitters
# ---------------------------------------------------------------------------


def _emit_goal_vba(
    *,
    function_type: str,
    operator: str,
    target,
    freq_ghz: float = None,
    freq_range=None,
    weight: float = 1.0,
    comment: str = "",
) -> str:
    """Return a single ``With Optimizer1D … End With`` block adding one goal.

    ``operator`` is one of ``"<"``, ``">"``, ``"="``, ``"minimize"``,
    ``"maximize"``. In CST the API names vary across versions; the block
    below picks the conservative set that has been supported since CST
    2021.
    """
    lines: List[str] = [
        "Dim goalID As Long",
        "With Optimizer",
        ' goalID = .AddGoal("1DC Primary Result")',
        " .SelectGoal goalID, True",
        ' .SetGoal1DCResultName "1D Results\\S-Parameters\\S1,1"',
        ' .SetGoalScalarType "magdB20"',
        f' .SetGoalOperator "{_operator_token(operator)}"',
    ]
    if freq_range is not None:
        start_ghz = _fmt_number(freq_range[0])
        stop_ghz = _fmt_number(freq_range[1])
        lines.append(' .SetGoalRangeType "range"')
        lines.append(f" .SetGoalRange {start_ghz}, {stop_ghz}")
    elif freq_ghz is not None:
        point = _fmt_number(freq_ghz)
        lines.append(' .SetGoalRangeType "single"')
        lines.append(f" .SetGoalRange {point}, {point}")
    if target is not None:
        lines.append(f" .SetGoalTarget {_fmt_number(target)}")
    lines.append(f" .SetGoalWeight {_fmt_number(weight)}")
    if comment:
        lines.append(f" ' {comment}")
    lines.append("End With")
    return "\n".join(lines) + "\n"


def _fmt_number(value: float) -> str:
    """Format a numeric value for inclusion in CST VBA quoted strings.

    Uses 9 significant digits and strips trailing zeros so values like
    ``2.45 - 0.05`` render as ``"2.4"`` instead of ``"2.4000000000000004"``.
    """
    if value is None:
        return ""
    text = f"{float(value):.9g}"
    return text


def _operator_token(op: str) -> str:
    mapping = {
        "<": "<",
        ">": ">",
        "=": "=",
        "minimize": "min",
        "maximize": "max",
    }
    return mapping.get(op, op)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_float(args: Dict[str, Any], key: str) -> float:
    if key not in args:
        raise ValueError(f"Missing required goal argument: {key!r}")
    try:
        return float(args[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Goal argument {key!r} must be numeric; got {args[key]!r}"
        ) from exc


__all__ = ["GOAL_TEMPLATES", "GoalPlan", "build_goal_plan"]
