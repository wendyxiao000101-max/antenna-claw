"""
Geometry topology checker for LEAM-generated CST VBA macros.

Parses the generated .bas files and detects structural issues that would
cause incorrect simulation results (wrong port connectivity, missing via
holes, orphan vacuum solids, hardcoded literals, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TopoIssue:
    """A single topology problem found during checking."""

    severity: str        # "error" | "warning" | "info"
    code: str            # short machine-readable code
    title: str           # one-line summary (Chinese)
    message: str         # detailed description (Chinese)
    suggestion: str      # concrete fix guidance (Chinese)
    affected: str = ""   # name of the affected solid

    def format(self) -> str:
        icon = {"error": "[错误]", "warning": "[警告]", "info": "[提示]"}.get(
            self.severity, "[?]"
        )
        lines = [f"{icon} {self.title}"]
        if self.affected:
            lines.append(f"         影响对象: {self.affected}")
        lines.append(f"         {self.message}")
        lines.append(f"   → 建议修复: {self.suggestion}")
        return "\n".join(lines)

    def as_llm_context(self) -> str:
        """Compact form suitable for injecting into an LLM prompt."""
        return (
            f"[{self.code}] {self.title} | "
            f"影响: {self.affected or '—'} | "
            f"修复: {self.suggestion}"
        )


@dataclass
class SolidDef:
    """Extracted definition of one CST solid."""

    solid_type: str                          # "Brick" | "Cylinder" | "Extrude" | …
    name: str
    component: str = "component1"
    material: str = ""
    props: Dict[str, str] = field(default_factory=dict)

    def full_name(self) -> str:
        return f"{self.component}:{self.name}"


# ---------------------------------------------------------------------------
# VBA parsers
# ---------------------------------------------------------------------------

def parse_vba_solids(vba_text: str) -> List[SolidDef]:
    """Extract solid definitions from ``With <Type> … End With`` blocks.

    Handles multi-argument properties (e.g. ``.Xrange "a", "b"``) by storing
    them as ``"a,b"`` in the props dict.
    """
    solids: List[SolidDef] = []

    block_re = re.compile(
        r"With\s+(\w+)\s*\n(.*?)End\s+With",
        re.DOTALL | re.IGNORECASE,
    )
    prop_re = re.compile(
        r"\.([\w]+)\s+\"([^\"]*)\"\s*(?:,\s*\"([^\"]*)\")?"
    )

    for block in block_re.finditer(vba_text):
        solid_type = block.group(1).strip()
        body = block.group(2)

        props: Dict[str, str] = {}
        for pm in prop_re.finditer(body):
            key = pm.group(1).lower()
            v1 = pm.group(2)
            v2 = pm.group(3)
            props[key] = f"{v1},{v2}" if v2 is not None else v1

        name = props.get("name", "")
        if not name:
            continue  # skip non-solid With blocks (e.g. With Units)

        solids.append(
            SolidDef(
                solid_type=solid_type,
                name=name,
                component=props.get("component", "component1"),
                material=props.get("material", ""),
                props=props,
            )
        )

    return solids


def parse_parameters(param_vba: str) -> Dict[str, str]:
    """Extract ``name → value`` from a *parameters.bas* file.

    Handles both the array style (``names(n) = "…"  values(n) = "…"``) and
    the ``StoreParameter "name", "value"`` style.
    """
    params: Dict[str, str] = {}

    name_re = re.compile(r'names\s*\(\s*(\d+)\s*\)\s*=\s*"([^"]+)"', re.IGNORECASE)
    val_re = re.compile(r'values\s*\(\s*(\d+)\s*\)\s*=\s*"([^"]+)"', re.IGNORECASE)

    idx_names: Dict[int, str] = {}
    idx_vals: Dict[int, str] = {}
    for m in name_re.finditer(param_vba):
        idx_names[int(m.group(1))] = m.group(2)
    for m in val_re.finditer(param_vba):
        idx_vals[int(m.group(1))] = m.group(2)
    for idx, pname in idx_names.items():
        if idx in idx_vals:
            params[pname] = idx_vals[idx]

    # StoreParameter style
    for m in re.finditer(
        r'StoreParameter\s+"([^"]+)"\s*,\s*"([^"]+)"', param_vba, re.IGNORECASE
    ):
        params[m.group(1)] = m.group(2)

    return params


def parse_boolean_ops(bool_vba: str) -> List[Tuple[str, str, str]]:
    """Return ``(operation, target_solid, tool_solid)`` triples.

    Handles both ``With Solid … .Subtract "a","b" … End With`` and the
    standalone ``Solid.Subtract "a","b"`` forms.
    """
    ops: List[Tuple[str, str, str]] = []

    # Standalone: Solid.Subtract "…", "…"
    standalone_re = re.compile(
        r'Solid\s*\.\s*(Subtract|Add|Intersect|Insert|Imprint)\s+'
        r'"([^"]+)"\s*,\s*"([^"]+)"',
        re.IGNORECASE,
    )
    for m in standalone_re.finditer(bool_vba):
        ops.append((m.group(1), m.group(2), m.group(3)))

    # With Solid block: .Subtract "…", "…"
    block_re = re.compile(
        r"With\s+Solid\s*\n(.*?)End\s+With", re.DOTALL | re.IGNORECASE
    )
    inner_re = re.compile(
        r"\.(Subtract|Add|Intersect|Insert|Imprint)\s+"
        r'"([^"]+)"\s*,\s*"([^"]+)"',
        re.IGNORECASE,
    )
    for block in block_re.finditer(bool_vba):
        for m in inner_re.finditer(block.group(1)):
            ops.append((m.group(1), m.group(2), m.group(3)))

    return ops


# ---------------------------------------------------------------------------
# Material / shape helpers
# ---------------------------------------------------------------------------

def _is_copper(mat: str) -> bool:
    return bool(re.search(r"copper|pec|metal", mat, re.IGNORECASE))


def _is_vacuum(mat: str) -> bool:
    return bool(re.search(r"vacuum", mat, re.IGNORECASE))


def _is_dielectric(mat: str) -> bool:
    return bool(re.search(r"fr[-\s]?4|rogers|substrate|dielectric|epoxy", mat, re.IGNORECASE))


def _expr_starts_negative(expr: str) -> bool:
    """Return True when the CST expression clearly starts with a negative term."""
    return expr.strip().startswith("-")


# ---------------------------------------------------------------------------
# Check 1 — Via z-range completeness
# ---------------------------------------------------------------------------

_VIA_KEYWORDS = ("via", "feed", "short", "pin", "probe", "signal")


def check_via_completeness(solids: List[SolidDef]) -> List[TopoIssue]:
    """Copper Cylinder vias must extend below z = 0 (into the bottom copper layer).

    A via whose Zrange minimum is ``"0"`` or positive cannot contact the
    bottom ground plane and will not form a proper port reference.
    """
    issues: List[TopoIssue] = []

    for s in solids:
        if s.solid_type.lower() != "cylinder":
            continue
        if not _is_copper(s.material):
            continue
        if s.props.get("axis", "").lower() not in ("z", ""):
            continue  # not a vertical via
        if not any(kw in s.name.lower() for kw in _VIA_KEYWORDS):
            continue

        zrange = s.props.get("zrange", "")
        if not zrange:
            continue
        parts = zrange.split(",", 1)
        if len(parts) < 2:
            continue
        zmin_expr = parts[0].strip()

        if not _expr_starts_negative(zmin_expr):
            issues.append(
                TopoIssue(
                    severity="error",
                    code="VIA_ZMIN_INCOMPLETE",
                    title=f"导通柱 '{s.name}' 未穿透地层",
                    message=(
                        f"Cylinder '{s.name}' 的 Zrange 下限为 \"{zmin_expr}\"，"
                        f"未延伸到底层铜箔（z < 0）以下。"
                        f"馈电柱/接地柱必须从 -t_cu（或更低）开始，"
                        f"否则端口无法连接到地参考面，导致 S 参数异常。"
                    ),
                    suggestion=(
                        f"将 .Zrange 的下限改为 \"-t_cu\" 或 \"-t_cu - viaBottomOverlap\"，"
                        f"使导通柱延伸到底层铜箔内部。"
                    ),
                    affected=s.name,
                )
            )

    return issues


# ---------------------------------------------------------------------------
# Check 2 — Substrate via holes
# ---------------------------------------------------------------------------

def check_substrate_via_holes(
    solids: List[SolidDef],
    bool_ops: List[Tuple[str, str, str]],
) -> List[TopoIssue]:
    """Every copper via that passes through the dielectric substrate must have
    a matching Vacuum cylinder subtracted from the substrate.

    Without the hole, the via and substrate overlap topologically, producing
    unreliable mesh generation and potentially wrong current paths.
    """
    issues: List[TopoIssue] = []

    substrate_full_names = {
        s.full_name()
        for s in solids
        if s.solid_type.lower() == "brick" and _is_dielectric(s.material)
    }

    vacuum_cyls = [
        s for s in solids
        if s.solid_type.lower() == "cylinder" and _is_vacuum(s.material)
    ]

    # Tools that are subtracted from substrate solids
    subtracted_from_sub = {
        tool
        for op, target, tool in bool_ops
        if op.lower() == "subtract" and target in substrate_full_names
    }

    copper_vias = [
        s for s in solids
        if s.solid_type.lower() == "cylinder"
        and _is_copper(s.material)
        and any(kw in s.name.lower() for kw in _VIA_KEYWORDS)
    ]

    for via in copper_vias:
        xc = via.props.get("xcenter", "")
        yc = via.props.get("ycenter", "")

        # Find any Vacuum cylinder whose center matches this via
        holes = [
            v for v in vacuum_cyls
            if v.props.get("xcenter", "") == xc
            and v.props.get("ycenter", "") == yc
            # Accept if it spans some positive z range (inside substrate)
        ]

        # Only keep holes whose z-range overlaps the substrate (Zmin >= 0 or mid in 0…h_sub)
        substrate_holes = [
            h for h in holes
            if not _expr_starts_negative(
                h.props.get("zrange", "0,0").split(",")[0].strip()
            )
        ]

        if not substrate_holes:
            r = via.props.get("outerradius", "rVia")
            issues.append(
                TopoIssue(
                    severity="error",
                    code="SUBSTRATE_NO_VIA_HOLE",
                    title=f"基板未为 '{via.name}' 开孔",
                    message=(
                        f"导通柱 '{via.name}'（Xcenter={xc}, Ycenter={yc}）"
                        f"穿过基板，但基板中无对应的 Vacuum 圆柱孔。"
                        f"实体重叠会导致网格冲突，仿真结果不可靠。"
                    ),
                    suggestion=(
                        f"在 model.bas 中添加 Vacuum 圆柱"
                        f"（Xcenter={xc}, Ycenter={yc}, OuterRadius≥{r}, "
                        f"Zrange=\"0\",\"h_sub\"），"
                        f"并在 boolean_ops.bas 中将其从基板中减去。"
                    ),
                    affected=via.name,
                )
            )
        else:
            # Hole exists — check it's actually subtracted
            subtracted = any(
                h.full_name() in subtracted_from_sub for h in substrate_holes
            )
            if not subtracted and substrate_full_names:
                sub_example = next(iter(substrate_full_names))
                hole_name = substrate_holes[0].full_name()
                issues.append(
                    TopoIssue(
                        severity="warning",
                        code="VIA_HOLE_NOT_SUBTRACTED",
                        title=f"'{via.name}' 的基板孔未执行布尔减操作",
                        message=(
                            f"为 '{via.name}' 定义了 Vacuum 圆柱 '{substrate_holes[0].name}'，"
                            f"但 boolean_ops.bas 中未将其从基板减去。"
                            f"几何上导通柱与基板仍然重叠。"
                        ),
                        suggestion=(
                            f"在 boolean_ops.bas 中添加: "
                            f"Solid.Subtract \"{sub_example}\", \"{hole_name}\""
                        ),
                        affected=via.name,
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# Check 3 — Feed via clearance in ground plane
# ---------------------------------------------------------------------------

_FEED_KEYWORDS = ("feed", "probe", "signal", "port")


def check_feed_clearance(
    solids: List[SolidDef],
    bool_ops: List[Tuple[str, str, str]],
) -> List[TopoIssue]:
    """The feed via must have a clearance gap in the bottom copper ground plane.

    Without this gap the via is short-circuited to ground at the bottom face,
    making it impossible to excite the antenna through a discrete port.
    The clearance cylinder must be subtracted from the ground plane in
    boolean_ops.bas.
    """
    issues: List[TopoIssue] = []

    ground_full_names = {
        s.full_name()
        for s in solids
        if s.solid_type.lower() == "brick"
        and _is_copper(s.material)
        and any(kw in s.name.lower() for kw in ("ground", "gnd", "bottom", "backplane"))
    }

    vacuum_cyls = [
        s for s in solids
        if s.solid_type.lower() == "cylinder" and _is_vacuum(s.material)
    ]

    subtracted_from_gnd = {
        tool
        for op, target, tool in bool_ops
        if op.lower() == "subtract" and target in ground_full_names
    }

    feed_vias = [
        s for s in solids
        if s.solid_type.lower() == "cylinder"
        and _is_copper(s.material)
        and any(kw in s.name.lower() for kw in _FEED_KEYWORDS)
    ]

    for via in feed_vias:
        xc = via.props.get("xcenter", "")
        yc = via.props.get("ycenter", "")

        # Clearance = vacuum cylinder at same center that spans the ground layer (z<0)
        clearances = [
            v for v in vacuum_cyls
            if v.props.get("xcenter", "") == xc
            and v.props.get("ycenter", "") == yc
            and _expr_starts_negative(
                v.props.get("zrange", "0,0").split(",")[0].strip()
            )
        ]

        cleared = any(c.full_name() in subtracted_from_gnd for c in clearances)

        if not cleared and ground_full_names:
            has_clearance_solid = bool(clearances)
            if not has_clearance_solid:
                issues.append(
                    TopoIssue(
                        severity="error",
                        code="FEED_NO_GROUND_CLEARANCE",
                        title=f"馈电柱 '{via.name}' 与地层间无间隙",
                        message=(
                            f"馈电柱 '{via.name}' 穿过地层，但地层中没有对应间隙孔，"
                            f"导通柱将与地层短路，端口无法正常激励，S 参数将趋近于 0 dB。"
                        ),
                        suggestion=(
                            f"在 model.bas 中添加 Vacuum 圆柱"
                            f"（Xcenter={xc}, Ycenter={yc}, OuterRadius=rFeedGndClear, "
                            f"Zrange=\"-t_cu\",\"0\"），"
                            f"并在 boolean_ops.bas 中从地层减去它。"
                        ),
                        affected=via.name,
                    )
                )
            else:
                # Clearance solid exists but not subtracted
                issues.append(
                    TopoIssue(
                        severity="warning",
                        code="FEED_CLEARANCE_NOT_SUBTRACTED",
                        title=f"馈电间隙孔未从地层减去",
                        message=(
                            f"'{clearances[0].name}' 是 '{via.name}' 的地层间隙孔，"
                            f"但 boolean_ops.bas 中未将其从地层减去。"
                        ),
                        suggestion=(
                            f"在 boolean_ops.bas 中添加: "
                            f"Solid.Subtract \"{next(iter(ground_full_names))}\", "
                            f"\"{clearances[0].full_name()}\""
                        ),
                        affected=via.name,
                    )
                )

    return issues


# ---------------------------------------------------------------------------
# Check 4 — Orphan Vacuum solids
# ---------------------------------------------------------------------------

def check_orphan_vacuum(
    solids: List[SolidDef],
    bool_ops: List[Tuple[str, str, str]],
) -> List[TopoIssue]:
    """Vacuum solids not referenced in any Boolean Subtract/Intersect/Insert
    are almost certainly forgotten cutouts that should be subtracted."""
    issues: List[TopoIssue] = []

    used_as_tool = {
        tool
        for op, _target, tool in bool_ops
        if op.lower() in ("subtract", "intersect", "insert")
    }

    for s in solids:
        if not _is_vacuum(s.material):
            continue
        if s.full_name() not in used_as_tool:
            issues.append(
                TopoIssue(
                    severity="warning",
                    code="ORPHAN_VACUUM",
                    title=f"Vacuum 体 '{s.name}' 未被布尔减去",
                    message=(
                        f"Vacuum 体 '{s.name}' 存在于模型中，"
                        f"但在 boolean_ops.bas 中没有任何布尔操作引用它。"
                        f"这通常意味着漏掉了一次 Solid.Subtract 调用。"
                    ),
                    suggestion=(
                        f"在 boolean_ops.bas 中添加 "
                        f"Solid.Subtract \"目标实体\", \"{s.full_name()}\"，"
                        f"或确认该体是否确实不需要布尔操作。"
                    ),
                    affected=s.name,
                )
            )

    return issues


# ---------------------------------------------------------------------------
# Check 5 — Hardcoded literal detection
# ---------------------------------------------------------------------------

_RANGE_PROPS = frozenset(
    {"xrange", "yrange", "zrange", "xcenter", "ycenter",
     "outerradius", "innerradius"}
)


def check_hardcoded_literals(
    solids: List[SolidDef],
    params: Dict[str, str],
) -> List[TopoIssue]:
    """Flag plain numeric literals in solid coordinate properties that exactly
    match a known parameter value — they should use the parameter name instead
    so the model stays parametrically linked when dimensions change."""
    issues: List[TopoIssue] = []

    # Build value → [name, …] map for purely numeric parameters
    val_to_names: Dict[str, List[str]] = {}
    for pname, pval in params.items():
        v = pval.strip()
        if re.fullmatch(r"[-+]?\d+(\.\d*)?", v):
            val_to_names.setdefault(v, []).append(pname)

    seen: set = set()  # avoid duplicate issues for same solid+property

    for s in solids:
        for key, val_str in s.props.items():
            if key not in _RANGE_PROPS:
                continue
            for part in val_str.split(","):
                token = part.strip()
                if token in val_to_names:
                    dedup_key = (s.name, key, token)
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    param_names = val_to_names[token]
                    issues.append(
                        TopoIssue(
                            severity="info",
                            code="HARDCODED_LITERAL",
                            title=f"'{s.name}' 存在可参数化的硬编码数值",
                            message=(
                                f"实体 '{s.name}' 的 .{key.capitalize()} "
                                f"使用了字面量 \"{token}\"，"
                                f"该值与参数 {param_names} 的值相同。"
                                f"参数修改后此坐标不会自动更新。"
                            ),
                            suggestion=(
                                f"将 \"{token}\" 替换为参数名 \"{param_names[0]}\"（或其表达式）。"
                            ),
                            affected=s.name,
                        )
                    )

    return issues


# ---------------------------------------------------------------------------
# Topology classification
# ---------------------------------------------------------------------------

def _has_via_through_substrate(solids: List[SolidDef]) -> bool:
    """Return True when the model contains a PIFA-like topology: at least one
    dielectric substrate brick AND at least one copper cylinder that looks like
    a through-substrate via/feed/short pin.  Only in this topology do the four
    via-related checks (VIA_ZMIN_INCOMPLETE, SUBSTRATE_NO_VIA_HOLE,
    FEED_NO_GROUND_CLEARANCE, ORPHAN_VACUUM) make sense.
    """
    has_substrate = any(
        s.solid_type.lower() == "brick" and _is_dielectric(s.material)
        for s in solids
    )
    has_copper_via = any(
        s.solid_type.lower() == "cylinder"
        and _is_copper(s.material)
        and any(kw in s.name.lower() for kw in _VIA_KEYWORDS)
        for s in solids
    )
    return has_substrate and has_copper_via


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_topology_checks(
    param_vba: str,
    model_vba: str,
    bool_vba: str,
) -> List[TopoIssue]:
    """Run all topology checks and return issues sorted by severity.

    Via-related checks (VIA_ZMIN_INCOMPLETE, SUBSTRATE_NO_VIA_HOLE,
    FEED_NO_GROUND_CLEARANCE, ORPHAN_VACUUM) only execute when the model
    contains a PIFA-like topology — a dielectric substrate brick with copper
    cylinder vias passing through it.  HARDCODED_LITERAL always runs.

    Args:
        param_vba:  Content of ``*_parameters.bas``
        model_vba:  Content of ``*_model.bas``
        bool_vba:   Content of ``*_boolean.bas``

    Returns:
        List of :class:`TopoIssue`, errors first then warnings then info.
    """
    solids = parse_vba_solids(model_vba)
    params = parse_parameters(param_vba)
    bool_ops = parse_boolean_ops(bool_vba)

    all_issues: List[TopoIssue] = []

    if _has_via_through_substrate(solids):
        all_issues.extend(check_via_completeness(solids))
        all_issues.extend(check_substrate_via_holes(solids, bool_ops))
        all_issues.extend(check_feed_clearance(solids, bool_ops))
        all_issues.extend(check_orphan_vacuum(solids, bool_ops))

    all_issues.extend(check_hardcoded_literals(solids, params))

    _order = {"error": 0, "warning": 1, "info": 2}
    all_issues.sort(key=lambda x: _order.get(x.severity, 3))
    return all_issues


def format_report(issues: List[TopoIssue]) -> str:
    """Render issues as a human-readable report string."""
    if not issues:
        return "[拓扑自检] ✓ 未发现几何拓扑问题，模型结构正常。"

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    header = (
        f"[拓扑自检] 发现 {len(errors)} 个错误 / "
        f"{len(warnings)} 个警告 / {len(infos)} 个提示"
    )
    sep = "=" * 60
    parts = [sep, header, sep]
    for issue in issues:
        parts.append("")
        parts.append(issue.format())
    parts.append("")
    return "\n".join(parts)


def build_fix_prompt(
    issues: List[TopoIssue],
    user_instructions: str = "",
) -> str:
    """Build a structured prompt block describing topology issues for the LLM.

    This is injected into the regeneration description so the model knows
    exactly what to fix.
    """
    actionable = [i for i in issues if i.severity in ("error", "warning")]
    if not actionable and not user_instructions:
        return ""

    lines = [
        "=== 几何拓扑自检结果（必须在重新生成时全部修复）===",
        "",
    ]
    for issue in actionable:
        lines.append(issue.as_llm_context())
    lines.append("")

    codes = {i.code for i in actionable}
    lines.append("=== 强制修复规则 ===")
    rule_num = 0
    if codes & {"VIA_ZMIN_INCOMPLETE"}:
        rule_num += 1
        lines.append(
            f"{rule_num}. 每个穿透基板的铜柱（Via）必须从 -t_cu（或更低）延伸到顶铜层以上。"
        )
    if codes & {"SUBSTRATE_NO_VIA_HOLE", "VIA_HOLE_NOT_SUBTRACTED"}:
        rule_num += 1
        lines.append(
            f"{rule_num}. 每个穿透基板的铜柱，必须在基板中有一个对应的 Vacuum 圆柱孔，"
            "并在 boolean_ops.bas 中执行 Solid.Subtract。"
        )
    if codes & {"FEED_NO_GROUND_CLEARANCE", "FEED_CLEARANCE_NOT_SUBTRACTED"}:
        rule_num += 1
        lines.append(
            f"{rule_num}. 馈电柱在地层处必须有间隙孔（Vacuum 圆柱，Zrange=-t_cu,0），"
            "并在 boolean_ops.bas 中从地层减去，形成信号端与地参考的隔离。"
        )
    if codes & {"ORPHAN_VACUUM"}:
        rule_num += 1
        lines.append(
            f"{rule_num}. 所有 Vacuum 体必须在 boolean_ops.bas 中被正确布尔减去，"
            "不允许存在孤立的 Vacuum 实体。"
        )
    if codes & {"HARDCODED_LITERAL"}:
        rule_num += 1
        lines.append(
            f"{rule_num}. 所有坐标/尺寸必须使用参数名或参数表达式，禁止硬编码数字。"
        )

    if user_instructions:
        lines.append("")
        lines.append("=== 用户额外修改指令 ===")
        lines.append(user_instructions)

    lines.append("=== END ===")
    return "\n".join(lines)
