"""CLI rendering helpers (all print-focused functions)."""

from pathlib import Path
from typing import Dict, List

from ..postprocess.topology_checker import parse_boolean_ops, parse_vba_solids

WIDTH = 66


def separator(char: str = "=") -> None:
    print(char * WIDTH)


def titled_section(title: str) -> None:
    separator()
    print(f"  {title}")
    separator("-")


def render_design_intent(intent: dict) -> None:
    titled_section("设计意图分析")
    print(f"  天线类型    : {intent.get('antenna_type', '—')}")
    print(f"  目标频率    : {intent.get('target_frequency', '—')}")
    bandwidth = intent.get("bandwidth")
    if bandwidth:
        print(f"  目标带宽    : {bandwidth}")
    substrate = intent.get("substrate") or {}
    print(
        f"  基板材料    : {substrate.get('material','—')}  "
        f"厚度 {substrate.get('thickness_mm','—')} mm"
    )
    conductor = intent.get("conductor") or {}
    print(
        f"  导体材料    : {conductor.get('material','—')}  "
        f"厚度 {conductor.get('thickness_mm','—')} mm"
    )
    print(f"  馈电方式    : {intent.get('feeding_method', '—')}")
    dimension_constraints = intent.get("dimension_constraints")
    if dimension_constraints:
        print(f"  尺寸限制    : {dimension_constraints}")

    separator("-")
    print("  结构说明:")
    for sentence in (intent.get("structure_overview") or "").split(". "):
        sentence = sentence.strip().rstrip(".")
        if sentence:
            print(f"    {sentence}.")

    separator("-")
    print("  预期几何体:")
    for solid in intent.get("key_solids") or []:
        shape = (solid.get("shape") or "?")[:3].upper()
        print(f"    [{shape}]  {solid.get('name','?'):<26}{solid.get('role','')}")

    initial_parameters = intent.get("initial_parameters") or {}
    if initial_parameters:
        separator("-")
        print("  初始参数估算 (mm):")
        for key, value in initial_parameters.items():
            print(f"    {key:<22}= {value}")
    separator()


def render_parameter_table(params: List[Dict]) -> None:
    titled_section(f"参数表（共 {len(params)} 项）")
    print(f"  {'#':<4}  {'参数名':<22}  {'当前值':<18}  说明")
    print("  " + "-" * (WIDTH - 2))
    for param in params:
        comment = (param.get("comment") or "")[:30]
        print(
            f"  {param['idx']:<4}  {param['name']:<22}  "
            f"{param['value']:<18}  {comment}"
        )
    separator()


def render_geometry_plan(output_dir: Path, model_name: str, bool_name: str, mat_name: str) -> str:
    """Parse and display geometry/material/boolean summary.

    Returns a compact textual plan for follow-up LLM Q&A classification.
    """
    model_text = (output_dir / model_name).read_text(encoding="utf-8")
    bool_text = (output_dir / bool_name).read_text(encoding="utf-8")
    mat_text = (output_dir / mat_name).read_text(encoding="utf-8")

    solids = parse_vba_solids(model_text)
    bool_ops = parse_boolean_ops(bool_text)
    mat_names = _extract_material_names(mat_text)

    titled_section("几何 & 材料方案（请确认后继续）")
    print("  [材料]")
    for material in mat_names:
        print(f"    • {material}")
    print()

    print("  [几何体]")
    print(f"  {'#':<3}  {'类型':<7}  {'名称':<28}  材料")
    print("  " + "-" * (WIDTH - 2))
    for idx, solid in enumerate(solids, 1):
        shape = solid.solid_type[:5].upper()
        print(f"  {idx:<3}  {shape:<7}  {solid.name:<28}  {solid.material}")
    print()

    print("  [布尔运算]")
    if bool_ops:
        for op, target, tool in bool_ops:
            target_name = target.split(":")[-1]
            tool_name = tool.split(":")[-1]
            symbol = "−" if op.lower() == "subtract" else "+"
            print(f"    {op.upper():<10}  {target_name}  {symbol}  {tool_name}")
    else:
        print("    （无）")
    separator()

    plan_lines = [
        "材料: " + ", ".join(mat_names),
        "几何体: " + "; ".join(
            f"{s.name}[{s.solid_type},{s.material}]" for s in solids
        ),
        "布尔: " + "; ".join(f"{op}({target},{tool})" for op, target, tool in bool_ops),
    ]
    return "\n".join(plan_lines)


def _extract_material_names(text: str) -> List[str]:
    import re

    return re.findall(r'\.Name\s+"([^"]+)"', text)

