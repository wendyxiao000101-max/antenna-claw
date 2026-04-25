import re
from pathlib import Path
from typing import Dict, List, Set


UNSAFE_PARAMETER_MAP = {
    "tand": "tan_delta",
    "tanD": "tan_delta",
    "epsr": "eps_r",
    "er": "eps_r",
    "hSub": "h_sub",
    "tCu": "t_cu",
}

STANDARD_MATERIAL_MAP = {
    "Rogers RO4350B": "Rogers RO4350B (lossy)",
    "RO4350B": "Rogers RO4350B (lossy)",
    "Copper": "Copper (pure)",
    "copper": "Copper (pure)",
    "PEC": "Copper (pure)",
}

SAFE_CUSTOM_SUBSTRATE_NAME = "SUBSTRATE_MAT"
SAFE_CONDUCTOR_NAME = "CONDUCTOR_MAT"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def normalize_parameter_names(text: str) -> str:
    """
    Replace unsafe parameter names only when they appear as standalone identifiers.
    Avoid global blind replace.
    """
    for old, new in UNSAFE_PARAMETER_MAP.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return text


def extract_created_material_names(materials_vba: str) -> Set[str]:
    """
    Extract material names created in materials.bas
    Matches lines like:
        .Name "Rogers RO4350B (lossy)"
    """
    return set(re.findall(r'\.Name\s+"([^"]+)"', materials_vba))


def extract_used_material_names(model_vba: str) -> Set[str]:
    """
    Extract material names referenced in model.bas
    Matches lines like:
        .Material "Copper (pure)"
    """
    return set(re.findall(r'\.Material\s+"([^"]+)"', model_vba))


def normalize_model_material_names(model_vba: str, created_materials: Set[str]) -> str:
    """
    Force model.bas to use only materials that actually exist in materials.bas.

    Rules:
    - Any CustomDielectric... -> if Rogers RO4350B (lossy) exists, use that
    - Copper / copper / PEC -> Copper (pure) if available
    """
    def repl(match):
        original = match.group(1)
        new_name = original

        if original.startswith("CustomDielectric"):
            if "Rogers RO4350B (lossy)" in created_materials:
                new_name = "Rogers RO4350B (lossy)"

        elif original in STANDARD_MATERIAL_MAP:
            mapped = STANDARD_MATERIAL_MAP[original]
            if mapped in created_materials:
                new_name = mapped

        return f'.Material "{new_name}"'

    return re.sub(r'\.Material\s+"([^"]+)"', repl, model_vba)


def extract_defined_parameters(parameters_vba: str) -> Set[str]:
    """
    Try to extract parameter names from VBA.
    Supports common patterns like:
        StoreParameter "f0_GHz", "2.45"
        MakeSureParameterExists "f0_GHz", "2.45"
    """
    names = set()
    names.update(re.findall(r'StoreParameter\s+"([^"]+)"', parameters_vba))
    names.update(re.findall(r'MakeSureParameterExists\s+"([^"]+)"', parameters_vba))
    return names


def extract_identifier_candidates(text: str) -> Set[str]:
    """
    Roughly collect identifier-like tokens from model/dim/json.
    This is a heuristic, not a full parser.
    """
    return set(re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', text))


def validate_material_consistency(materials_vba: str, model_vba: str) -> List[str]:
    created = extract_created_material_names(materials_vba)
    used = extract_used_material_names(model_vba)

    allowed_builtin_materials = {
        "Vacuum",
        "PEC",
    }

    missing = sorted(
        name for name in (used - created)
        if name not in allowed_builtin_materials
    )
    return [f"model.bas 引用了未创建的材料: {name}" for name in missing]


def validate_parameter_consistency(parameters_vba: str, dimension_json: str, model_vba: str) -> List[str]:
    defined = extract_defined_parameters(parameters_vba)
    used = extract_identifier_candidates(dimension_json) | extract_identifier_candidates(model_vba)

    # 这些是常见非参数词，避免误报过多
    ignore = {
    "With", "End", "Brick", "Material", "Component", "Name", "Create",
    "Xrange", "Yrange", "Zrange", "Reset", "Copper", "Rogers",
    "Substrate", "GroundPlane", "Patch", "Vacuum", "component1",
    "true", "false", "mm", "GHz",

    # 常见 VBA / CST 词
    "Boolean", "BooleanAdd", "BooleanSubtract", "Units", "Type",
    "Global", "Top", "Full", "Centered", "Connection", "Rectangular",
    "FeedLine", "RadiatorPatch", "PatchSlot_Cutout", "CustomDielectric",
    "RO4350B", "Xmin", "Xmax", "Ymin", "Ymax", "Zmin", "Zmax",

    # 常见材料/对象词
    "lossy", "pure", "Rogers4350B", "Ground", "Slot", "Feed", "Line",
}

    suspicious = sorted(
        token for token in used
        if token not in defined
        and token not in ignore
        and not token.startswith("component")
    )

    # 这里只做轻量提示，不全量拦截
    return [f"可能未定义的参数或标识符: {name}" for name in suspicious[:20]]


def normalize_and_validate_outputs(
    json_path: Path,
    param_path: Path,
    dim_path: Path,
    mat_path: Path,
    model_path: Path,
    bool_path: Path,
) -> List[str]:
    """
    1) 规范化危险参数名
    2) 统一 model.bas 中的材料名
    3) 校验材料和参数一致性
    Returns: list of validation messages. 空列表表示通过。
    """
    json_text = _read_text(json_path)
    param_text = _read_text(param_path)
    dim_text = _read_text(dim_path)
    mat_text = _read_text(mat_path)
    model_text = _read_text(model_path)
    bool_text = _read_text(bool_path)

    # 1. 参数名规范化
    json_text = normalize_parameter_names(json_text)
    param_text = normalize_parameter_names(param_text)
    dim_text = normalize_parameter_names(dim_text)
    mat_text = normalize_parameter_names(mat_text)
    model_text = normalize_parameter_names(model_text)
    bool_text = normalize_parameter_names(bool_text)

    # 2. 材料名统一
    created_materials = extract_created_material_names(mat_text)
    model_text = normalize_model_material_names(model_text, created_materials)

    # 写回
    _write_text(json_path, json_text)
    _write_text(param_path, param_text)
    _write_text(dim_path, dim_text)
    _write_text(mat_path, mat_text)
    _write_text(model_path, model_text)
    _write_text(bool_path, bool_text)

    # 3. 一致性校验
    errors: List[str] = []
    warnings: List[str] = []

    errors.extend(validate_material_consistency(mat_text, model_text))
    warnings.extend(validate_parameter_consistency(param_text, dim_text, model_text))

    for w in warnings:
        print(f"[warning] {w}")

    return errors