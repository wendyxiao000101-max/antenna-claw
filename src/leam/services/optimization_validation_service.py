"""Validate and normalize optimization requests from OpenClaw.

This is the LEAM-side guard that backs
``LeamService.validate_optimization_request`` and pre-checks every
``optimize_parameters`` call. It is intentionally strict:

- variables must exist in the project's ``ParameterList`` (read from
  the ``_parameters.bas`` seed values),
- ``min < max`` and (when supplied) ``min <= init <= max``,
- goal templates must come from :data:`GOAL_TEMPLATES`,
- goal args are unit-normalized (MHz / Hz → GHz) and range-validated,
- algorithm names are whitelisted against the list CST Optimizer1D
  accepts by default,
- numeric fields are coerced to ``float`` when they arrive as strings
  like ``"15.0"`` or ``"2.45 GHz"``.

Errors have a stable shape so OpenClaw can decide whether to ask the
user for clarification or retry silently::

    {"code": "VAR_NAME_UNKNOWN", "field": "variables[0].name",
     "message": "...", "suggestion": "..."}
"""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .optimization_goals import GOAL_TEMPLATES
from .parameter_service import ParameterService


DEFAULT_ALGORITHM = "Trust Region Framework"
ALLOWED_ALGORITHMS: Tuple[str, ...] = (
    "Trust Region Framework",
    "Nelder Mead Simplex",
    "Interpolated Quasi Newton",
    "Classic Powell",
    "Genetic Algorithm",
    "Particle Swarm Optimization",
)

# Allowed argument sets per goal template, used both for validation and
# for the project-context snapshot that OpenClaw consumes.
GOAL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "s11_min_at_frequency": {
        "required": ("frequency_ghz",),
        "optional": ("threshold_db", "weight"),
        "defaults": {"threshold_db": -10.0, "weight": 1.0},
        "description": (
            "在 frequency_ghz 频点处将 |S11| 压到 threshold_db (dB) 以下。"
        ),
    },
    "bandwidth_max_in_band": {
        "required": ("freq_start_ghz", "freq_stop_ghz"),
        "optional": ("threshold_db", "weight"),
        "defaults": {"threshold_db": -10.0, "weight": 1.0},
        "description": (
            "在 [freq_start_ghz, freq_stop_ghz] 区间内保持 |S11| <= threshold_db (dB)。"
        ),
    },
    "resonance_align_to_frequency": {
        "required": ("frequency_ghz",),
        "optional": ("tolerance_mhz", "weight"),
        "defaults": {"tolerance_mhz": 50.0, "weight": 1.0},
        "description": (
            "在 frequency_ghz ± tolerance_mhz/2 区间内把 |S11| 的最小值往中心推。"
        ),
    },
}

# Unit aliases used to normalize goal-arg inputs.
FREQ_UNIT_TO_GHZ: Dict[str, float] = {
    "hz": 1e-9,
    "khz": 1e-6,
    "mhz": 1e-3,
    "ghz": 1.0,
}


MAX_EVALUATIONS_BOUNDS = (1, 500)


def _error(code: str, field: str, message: str, suggestion: str = "") -> Dict[str, str]:
    return {
        "code": code,
        "field": field,
        "message": message,
        "suggestion": suggestion,
    }


class OptimizationValidationService:
    """Validate and normalize an optimization request.

    The service only ever reads the filesystem (no CST calls). It is
    meant to run during ``validate_optimization_request`` *and* as the
    first step of ``optimize_parameters`` so every execution path sees
    the same guarantees.
    """

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.project_root = Path(project_root) if project_root else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        request: Dict[str, Any],
        *,
        parameters_bas: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Validate a request dict.

        ``request`` is the OpenClaw-shaped payload (after the
        :class:`~leam.service_api.OptimizationRequest` dataclass, or
        raw JSON). ``parameters_bas`` points at the existing
        ``<output>_parameters.bas`` — when provided, variable names are
        cross-checked against its ``ParameterList``.

        Returns ``{"is_valid", "normalized", "errors", "warnings"}``.
        """
        errors: List[Dict[str, str]] = []
        warnings: List[Dict[str, str]] = []
        normalized: Dict[str, Any] = {
            "output_name": "",
            "variables": [],
            "goals": [],
            "algorithm": DEFAULT_ALGORITHM,
            "max_evaluations": 40,
            "use_current_as_init": True,
            "natural_language": "",
            "notes": "",
        }

        if not isinstance(request, dict):
            errors.append(
                _error(
                    "REQUEST_NOT_OBJECT",
                    "request",
                    "优化请求不是对象 (dict)。",
                    "检查 OpenClaw 抽取的 JSON 是否漏了外层 {}。",
                )
            )
            return self._wrap(normalized, errors, warnings)

        normalized["output_name"] = str(request.get("output_name", "")).strip()
        normalized["natural_language"] = str(request.get("natural_language", ""))
        normalized["notes"] = str(request.get("notes", ""))

        if not normalized["output_name"]:
            errors.append(
                _error(
                    "OUTPUT_NAME_REQUIRED",
                    "output_name",
                    "必须提供 output_name 指向已存在的 LEAM 输出目录。",
                    "先执行一次 build_and_simulate 再复用其 output_name。",
                )
            )

        known_param_names = self._load_known_parameter_names(parameters_bas)
        normalized["known_parameters"] = sorted(known_param_names)

        normalized["variables"] = self._validate_variables(
            request.get("variables", []),
            known_param_names,
            errors,
            warnings,
        )
        normalized["goals"] = self._validate_goals(request.get("goals", []), errors, warnings)
        normalized["algorithm"] = self._validate_algorithm(
            request.get("algorithm"), warnings
        )
        normalized["max_evaluations"] = self._validate_max_evaluations(
            request.get("max_evaluations"), errors, warnings
        )
        normalized["use_current_as_init"] = bool(
            request.get("use_current_as_init", True)
        )

        return self._wrap(normalized, errors, warnings)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap(
        normalized: Dict[str, Any],
        errors: List[Dict[str, str]],
        warnings: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        return {
            "is_valid": not errors,
            "normalized": normalized,
            "errors": errors,
            "warnings": warnings,
        }

    @staticmethod
    def _load_known_parameter_names(parameters_bas: Optional[Path]) -> set:
        if parameters_bas is None:
            return set()
        try:
            text = parameters_bas.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return set()
        return {p["name"] for p in ParameterService.parse_bas(text) if p.get("name")}

    def _validate_variables(
        self,
        raw: Any,
        known_names: set,
        errors: List[Dict[str, str]],
        warnings: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            errors.append(
                _error(
                    "VARIABLES_REQUIRED",
                    "variables",
                    "variables 必须是一个至少包含一项的数组。",
                    "至少指明一个需要扫描的参数，含 min/max。",
                )
            )
            return []

        seen_names: set = set()
        cleaned: List[Dict[str, Any]] = []

        for idx, item in enumerate(raw):
            field_prefix = f"variables[{idx}]"
            if not isinstance(item, dict):
                errors.append(
                    _error(
                        "VARIABLE_NOT_OBJECT",
                        field_prefix,
                        "每个变量必须是一个 JSON 对象。",
                        '示例: {"name": "L", "min": 10, "max": 30}',
                    )
                )
                continue

            name = str(item.get("name", "")).strip()
            if not name:
                errors.append(
                    _error(
                        "VAR_NAME_REQUIRED",
                        f"{field_prefix}.name",
                        "变量 name 缺失。",
                        "从 project context 中的 parameters 列表选一个。",
                    )
                )
                continue
            if name in seen_names:
                errors.append(
                    _error(
                        "VAR_NAME_DUPLICATE",
                        f"{field_prefix}.name",
                        f"变量 {name!r} 在 variables 中重复出现。",
                        "合并或删除重复项。",
                    )
                )
                continue
            seen_names.add(name)

            if known_names and name not in known_names:
                errors.append(
                    _error(
                        "VAR_NAME_UNKNOWN",
                        f"{field_prefix}.name",
                        f"变量 {name!r} 不在当前 ParameterList 中。",
                        f"可选参数: {', '.join(sorted(known_names)) or '(无)'}。",
                    )
                )
                continue

            vmin, ok_min = _coerce_float(item.get("min"))
            vmax, ok_max = _coerce_float(item.get("max"))
            if not ok_min:
                errors.append(
                    _error(
                        "VAR_MIN_INVALID",
                        f"{field_prefix}.min",
                        f"变量 {name!r} 的 min 不是有效数值。",
                        "去掉单位后再提交，例如 min: 10 而不是 \"10mm\"。",
                    )
                )
                continue
            if not ok_max:
                errors.append(
                    _error(
                        "VAR_MAX_INVALID",
                        f"{field_prefix}.max",
                        f"变量 {name!r} 的 max 不是有效数值。",
                        "去掉单位后再提交。",
                    )
                )
                continue
            if vmin >= vmax:
                errors.append(
                    _error(
                        "VAR_RANGE_INVERTED",
                        f"{field_prefix}",
                        f"变量 {name!r} 的 min >= max ({vmin} vs {vmax})。",
                        "确保扫描范围 min < max。",
                    )
                )
                continue

            init_val: Optional[float] = None
            if "init" in item and item["init"] is not None:
                init_val, ok_init = _coerce_float(item["init"])
                if not ok_init:
                    errors.append(
                        _error(
                            "VAR_INIT_INVALID",
                            f"{field_prefix}.init",
                            f"变量 {name!r} 的 init 不是有效数值。",
                            "填入 min 与 max 之间的起始值即可。",
                        )
                    )
                    continue
                if init_val < vmin or init_val > vmax:
                    warnings.append(
                        _error(
                            "VAR_INIT_OUT_OF_RANGE",
                            f"{field_prefix}.init",
                            f"变量 {name!r} 的 init={init_val} 不在 [{vmin}, {vmax}] 之内。",
                            "建议把 init 夹到扫描范围内以加速收敛。",
                        )
                    )

            cleaned_var: Dict[str, Any] = {
                "name": name,
                "min": vmin,
                "max": vmax,
            }
            if init_val is not None:
                cleaned_var["init"] = init_val
            cleaned.append(cleaned_var)

        return cleaned

    def _validate_goals(
        self,
        raw: Any,
        errors: List[Dict[str, str]],
        warnings: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            errors.append(
                _error(
                    "GOALS_REQUIRED",
                    "goals",
                    "goals 必须是一个至少包含一项的数组。",
                    f"可用模板: {', '.join(GOAL_TEMPLATES)}。",
                )
            )
            return []

        cleaned: List[Dict[str, Any]] = []
        for idx, item in enumerate(raw):
            prefix = f"goals[{idx}]"
            if not isinstance(item, dict):
                errors.append(
                    _error(
                        "GOAL_NOT_OBJECT",
                        prefix,
                        "每个 goal 必须是 {template, args} 对象。",
                        '示例: {"template": "s11_min_at_frequency", "args": {"frequency_ghz": 2.4}}',
                    )
                )
                continue

            template = str(item.get("template", "")).strip()
            if not template:
                errors.append(
                    _error(
                        "GOAL_TEMPLATE_REQUIRED",
                        f"{prefix}.template",
                        "goal.template 缺失。",
                        f"从白名单选: {', '.join(GOAL_TEMPLATES)}。",
                    )
                )
                continue
            if template not in GOAL_TEMPLATES:
                errors.append(
                    _error(
                        "GOAL_TEMPLATE_UNKNOWN",
                        f"{prefix}.template",
                        f"goal.template={template!r} 不在白名单。",
                        f"可选: {', '.join(GOAL_TEMPLATES)}。",
                    )
                )
                continue

            args = item.get("args", {})
            if not isinstance(args, dict):
                errors.append(
                    _error(
                        "GOAL_ARGS_NOT_OBJECT",
                        f"{prefix}.args",
                        "goal.args 必须是一个对象。",
                        "请把关键参数放到 args 下面。",
                    )
                )
                continue

            cleaned_args = self._normalize_goal_args(template, args, prefix, errors, warnings)
            if cleaned_args is None:
                continue

            cleaned.append({"template": template, "args": cleaned_args})

        return cleaned

    def _normalize_goal_args(
        self,
        template: str,
        args: Dict[str, Any],
        prefix: str,
        errors: List[Dict[str, str]],
        warnings: List[Dict[str, str]],
    ) -> Optional[Dict[str, Any]]:
        schema = GOAL_SCHEMA[template]
        cleaned = deepcopy(schema["defaults"])

        # Normalize frequency-like keys first: accept *_ghz / *_mhz / *_hz.
        args = _normalize_frequency_aliases(args)

        for required in schema["required"]:
            if required not in args:
                errors.append(
                    _error(
                        "GOAL_ARG_REQUIRED",
                        f"{prefix}.args.{required}",
                        f"goal {template!r} 缺少必填参数 {required!r}。",
                        f"示例: {_example_for_goal(template)}",
                    )
                )
                return None

        for key, raw_val in args.items():
            if key not in schema["required"] and key not in schema["optional"]:
                warnings.append(
                    _error(
                        "GOAL_ARG_UNKNOWN",
                        f"{prefix}.args.{key}",
                        f"goal {template!r} 不接受参数 {key!r}，已忽略。",
                        f"可用字段: {', '.join(schema['required'] + schema['optional'])}。",
                    )
                )
                continue
            val, ok = _coerce_float(raw_val)
            if not ok:
                errors.append(
                    _error(
                        "GOAL_ARG_INVALID",
                        f"{prefix}.args.{key}",
                        f"goal 参数 {key!r} 不是数值: {raw_val!r}。",
                        "直接填写数字即可，不要附带单位。",
                    )
                )
                return None
            cleaned[key] = val

        # Template-specific sanity checks.
        if template == "bandwidth_max_in_band":
            if cleaned["freq_stop_ghz"] <= cleaned["freq_start_ghz"]:
                errors.append(
                    _error(
                        "GOAL_RANGE_INVERTED",
                        f"{prefix}.args",
                        "freq_stop_ghz 必须 > freq_start_ghz。",
                        "检查起止频率是否写反了。",
                    )
                )
                return None

        if template == "resonance_align_to_frequency":
            if cleaned.get("tolerance_mhz", 0) <= 0:
                errors.append(
                    _error(
                        "GOAL_TOLERANCE_INVALID",
                        f"{prefix}.args.tolerance_mhz",
                        "tolerance_mhz 必须为正数。",
                        "例如 50 表示 ±50 MHz 搜索窗。",
                    )
                )
                return None

        if "threshold_db" in cleaned and cleaned["threshold_db"] > 0:
            warnings.append(
                _error(
                    "GOAL_THRESHOLD_SIGN",
                    f"{prefix}.args.threshold_db",
                    f"threshold_db={cleaned['threshold_db']} 为正值，通常应为负数。",
                    "|S11| < -10 dB 代表反射低于 -10 dB。",
                )
            )

        return cleaned

    def _validate_algorithm(
        self,
        raw: Any,
        warnings: List[Dict[str, str]],
    ) -> str:
        if raw is None or not str(raw).strip():
            return DEFAULT_ALGORITHM
        value = str(raw).strip()
        if value not in ALLOWED_ALGORITHMS:
            warnings.append(
                _error(
                    "ALGORITHM_UNKNOWN",
                    "algorithm",
                    f"algorithm={value!r} 不在已知白名单，已回退 {DEFAULT_ALGORITHM!r}。",
                    f"支持: {', '.join(ALLOWED_ALGORITHMS)}。",
                )
            )
            return DEFAULT_ALGORITHM
        return value

    def _validate_max_evaluations(
        self,
        raw: Any,
        errors: List[Dict[str, str]],
        warnings: List[Dict[str, str]],
    ) -> int:
        if raw is None:
            return 40
        try:
            value = int(raw)
        except (TypeError, ValueError):
            errors.append(
                _error(
                    "MAX_EVAL_INVALID",
                    "max_evaluations",
                    f"max_evaluations={raw!r} 不是整数。",
                    "建议 10-200 之间。",
                )
            )
            return 40
        low, high = MAX_EVALUATIONS_BOUNDS
        if value < low:
            warnings.append(
                _error(
                    "MAX_EVAL_TOO_LOW",
                    "max_evaluations",
                    f"max_evaluations={value} 偏小，可能提前停止。",
                    f"建议 >= {low}。",
                )
            )
            value = low
        elif value > high:
            warnings.append(
                _error(
                    "MAX_EVAL_TOO_HIGH",
                    "max_evaluations",
                    f"max_evaluations={value} 偏大，可能耗时过久。",
                    f"建议 <= {high}。",
                )
            )
            value = high
        return value


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> Tuple[float, bool]:
    """Accept ``float``, ``int``, or a numeric-prefix string like ``"15mm"``."""
    if isinstance(value, bool):
        return 0.0, False
    if isinstance(value, (int, float)):
        return float(value), True
    if not isinstance(value, str):
        return 0.0, False
    stripped = value.strip()
    if not stripped:
        return 0.0, False
    match = re.match(r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", stripped)
    if not match:
        return 0.0, False
    try:
        return float(match.group(1)), True
    except ValueError:
        return 0.0, False


def _normalize_frequency_aliases(args: Dict[str, Any]) -> Dict[str, Any]:
    """Translate alternate unit keys to the canonical GHz keys.

    Only keys that contain ``frequency``, ``freq_start``, or
    ``freq_stop`` are affected, and only when a unit suffix is present.
    Canonical keys (``*_ghz``) take priority over alternates.
    """
    result = dict(args)
    aliases: Dict[str, Tuple[str, float]] = {}

    for key in list(result.keys()):
        canonical, factor = _match_frequency_alias(key)
        if canonical is None or factor is None:
            continue
        if canonical in result and canonical != key:
            continue
        aliases[key] = (canonical, factor)

    for original, (canonical, factor) in aliases.items():
        raw_val = result.pop(original)
        val, ok = _coerce_float(raw_val)
        if not ok:
            # leave as-is so the validator produces a clean GOAL_ARG_INVALID later
            result[canonical] = raw_val
            continue
        result[canonical] = val * factor
    return result


_FREQ_ALIAS_PATTERN = re.compile(
    r"^(frequency|freq_start|freq_stop)_(hz|khz|mhz|ghz)$",
    re.IGNORECASE,
)


def _match_frequency_alias(key: str) -> Tuple[Optional[str], Optional[float]]:
    m = _FREQ_ALIAS_PATTERN.match(str(key).strip())
    if not m:
        return None, None
    base = m.group(1).lower()
    unit = m.group(2).lower()
    canonical = f"{base}_ghz"
    return canonical, FREQ_UNIT_TO_GHZ.get(unit)


def _example_for_goal(template: str) -> str:
    examples = {
        "s11_min_at_frequency": '{"frequency_ghz": 2.4, "threshold_db": -10}',
        "bandwidth_max_in_band": '{"freq_start_ghz": 2.4, "freq_stop_ghz": 2.5, "threshold_db": -10}',
        "resonance_align_to_frequency": '{"frequency_ghz": 2.45, "tolerance_mhz": 50}',
    }
    return examples.get(template, "{...}")


__all__ = [
    "ALLOWED_ALGORITHMS",
    "DEFAULT_ALGORITHM",
    "GOAL_SCHEMA",
    "OptimizationValidationService",
]
