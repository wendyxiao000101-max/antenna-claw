"""Table rendering and non-interactive summary helpers for the air PIFA."""

from typing import Dict

from leam.templates.base_template import TemplateMetadata, ValidationResult

from .pifa_base import estimate_resonance
from .pifa_validator import is_param_editable, validate

WIDTH = 66

_PARAM_META = {
    "t_cu":  ("mm", "铜箔厚度"),
    "Lg":    ("mm", "地平面长度"),
    "Wg":    ("mm", "地平面宽度"),
    "h":     ("mm", "贴片高度"),
    "Lp":    ("mm", "贴片长度"),
    "Wp":    ("mm", "贴片宽度"),
    "dPin":  ("mm", "Pin 直径"),
    "sPins": ("mm", "馈电-短路间距"),
    "gPort": ("mm", "端口间隙"),
}

_DISPLAY_ORDER = ["t_cu", "Lg", "Wg", "h", "Lp", "Wp", "dPin", "sPins", "gPort"]


def _separator(char: str = "=") -> None:
    print(char * WIDTH)


def render_header(metadata: TemplateMetadata, target_ghz: float, strategy: str) -> None:
    print(f"\n=== {metadata.name} 模板 (v{metadata.version}) ===")
    print(f"目标频率:    {target_ghz} GHz")
    print(f"Baseline:    optimized_v1 ({metadata.baseline_frequency_ghz} GHz)")
    print(f"缩放策略:    {strategy}")


def render_table(
    params: Dict,
    metadata: TemplateMetadata,
    vr: ValidationResult,
    target_ghz: float,
) -> None:
    """Print the parameter table and validation summary."""
    _separator()
    n = len(_DISPLAY_ORDER)
    print(f"  参数表（共 {n} 项）")
    _separator("-")
    print(f"  {'#':<4}  {'参数名':<14}  {'当前值':<18}  {'单位':<6}  说明")
    print("  " + "-" * (WIDTH - 2))

    for idx, name in enumerate(_DISPLAY_ORDER, 1):
        unit, desc = _PARAM_META.get(name, ("", ""))
        val = params.get(name, 0)
        lock_tag = " [锁定]" if not is_param_editable(name, metadata) else ""
        print(
            f"  {idx:<4}  {name:<14}  {val:<18.6g}  {unit:<6}  {desc}{lock_tag}"
        )

    _separator()

    f_est = estimate_resonance(params)
    deviation = (f_est - target_ghz) / target_ghz * 100 if target_ghz else 0
    print(f"\n  估算谐振频率: {f_est:.2f} GHz (偏差 {deviation:+.1f}%)")

    if vr.errors:
        print("  校验结果: 存在错误")
        for e in vr.errors:
            print(f"    [错误] {e}")
    elif vr.warnings:
        print("  校验结果: 通过（有警告）")
        for w in vr.warnings:
            print(f"    [警告] {w}")
    else:
        print("  校验结果: 全部通过")
    print()


def review_summary(
    params: Dict,
    target_ghz: float,
    metadata: TemplateMetadata,
) -> Dict:
    """Render the parameter table and validation summary; return params unchanged.

    Non-interactive: no ``input()`` calls. Returned params are the same
    dict passed in, so the caller may feed them straight into
    ``BaseTemplate.generate``. OpenClaw is expected to handle any
    subsequent edit round by patching the generated .bas directly.
    """
    vr = validate(params, target_ghz)
    render_table(params, metadata, vr, target_ghz)

    editable_names = ", ".join(metadata.editable_params)
    if editable_names:
        print(f"可调参数: {editable_names}")
    return params
