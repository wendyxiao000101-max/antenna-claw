"""Parameter validation and edit-permission checks for the air PIFA template."""

from typing import List

from leam.templates.base_template import TemplateMetadata, ValidationResult

from .pifa_base import estimate_resonance


def is_param_editable(name: str, metadata: TemplateMetadata) -> bool:
    return name in metadata.editable_params


def validate(params: dict, target_ghz: float) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    t_cu = params.get("t_cu", 0)
    lg = params.get("Lg", 0)
    wg = params.get("Wg", 0)
    h = params.get("h", 0)
    lp = params.get("Lp", 0)
    wp = params.get("Wp", 0)
    d_pin = params.get("dPin", 0)
    s_pins = params.get("sPins", 0)
    g_port = params.get("gPort", 0)

    if t_cu <= 0:
        errors.append("t_cu 必须 > 0")
    if lp <= 0:
        errors.append("Lp 必须 > 0")
    if wp <= 0:
        errors.append("Wp 必须 > 0")
    if h <= 0:
        errors.append("h 必须 > 0")
    if h >= lp and lp > 0:
        errors.append(f"h ({h}) 应小于 Lp ({lp})")
    if d_pin <= 0:
        errors.append("dPin 必须 > 0")
    if lp > 0 and wp > 0 and d_pin >= min(lp, wp) / 2:
        errors.append(f"dPin ({d_pin}) 应小于 min(Lp,Wp)/2 ({min(lp,wp)/2:.3f})")
    if s_pins <= d_pin:
        errors.append(f"sPins ({s_pins}) 必须 > dPin ({d_pin})")
    if wp > 0 and s_pins >= wp:
        errors.append(f"sPins ({s_pins}) 必须 < Wp ({wp})")
    if g_port <= 0:
        errors.append("gPort 必须 > 0")
    if h > 0 and g_port >= h:
        errors.append(f"gPort ({g_port}) 必须 < h ({h})")
    if lp > 0 and lg < 2 * lp:
        warnings.append(f"Lg ({lg:.2f}) 建议 >= 2*Lp ({2*lp:.2f})")
    if wp > 0 and wg < 2 * wp:
        warnings.append(f"Wg ({wg:.2f}) 建议 >= 2*Wp ({2*wp:.2f})")

    f_est = estimate_resonance(params)
    if f_est > 0 and target_ghz > 0:
        deviation = abs(f_est - target_ghz) / target_ghz
        if deviation > 0.15:
            warnings.append(
                f"估算谐振 {f_est:.3f} GHz 与目标 {target_ghz:.3f} GHz "
                f"偏差 {deviation*100:.1f}%（>15%）"
            )

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
