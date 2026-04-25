import json
import os
import re
from typing import Any, Dict, List, Optional

from ..core.vba_generator import VBAGenerator
from ..utils.constants import DEFAULT_MODEL
from ..utils.file_io import resolve_save_dir
from ..utils.paths import prompt_path, resource_path


# ---------------------------------------------------------------------------
# Primitive-detection helpers
# ---------------------------------------------------------------------------

_PROFILE_PRIMITIVE_TOKENS = frozenset(
    {
        "profile",
        "polygon",
        "cutout",
        "taperedslot",
        "spline",
        "extrude",
        "25d",
        "2d",
    }
)

_PROFILE_KEYWORDS = (
    "extrude",
    "tapered slot",
    "taperedslot",
    "vivaldi",
    "ltsa",
    "polygon",
    "spline",
    "profile",
    "cutout",
    "2.5d",
)


def _tok(s: str) -> str:
    """Strip non-alphanumeric chars and lower-case — used for token comparison."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _is_profile_solid(solid: Dict[str, Any]) -> bool:
    """Return True when this solid needs profile-based (Extrude / Spline) VBA.

    Detection criteria (any one is sufficient):
    - dimensions.primitive is a profile token
    - dimensions.shape / geometry / profile_type contains a profile keyword
    - dimensions has an explicit profile_definition or profile_points list
    - Role contains "cutout"
    - notes / Type text contains "2.5d", "tapered slot", "vivaldi", or "profile"
    """
    dims = solid.get("dimensions") or {}
    if isinstance(dims, dict):
        prim = _tok(str(dims.get("primitive", "") or ""))
        if prim and prim in _PROFILE_PRIMITIVE_TOKENS:
            return True

        shape_text = " ".join(
            [
                str(dims.get("shape", "") or ""),
                str(dims.get("geometry", "") or ""),
                str(dims.get("profile_type", "") or ""),
            ]
        ).lower()
        if any(kw in shape_text for kw in _PROFILE_KEYWORDS):
            return True

        if dims.get("profile_definition") or dims.get("profile_points"):
            return True

    role = str(solid.get("Role", "") or "").lower()
    if "cutout" in role:
        return True

    misc_text = " ".join(
        [
            str(solid.get("notes", "") or ""),
            str(solid.get("Type", "") or ""),
        ]
    ).lower()
    if "2.5d" in misc_text or any(
        kw in misc_text for kw in ["tapered slot", "vivaldi", "profile"]
    ):
        return True

    return False


# ---------------------------------------------------------------------------
# Per-solid hint builder
# ---------------------------------------------------------------------------

def _tapered_slot_info(dims: Dict[str, Any]) -> Dict[str, str]:
    """Extract tapered-slot dimension parameters from a dims dict."""
    info: Dict[str, str] = {}
    for key in ("W_feed", "feed_gap", "slot_feed_width", "w_feed", "feed_width"):
        val = dims.get(key)
        if val is not None:
            info["W_feed"] = str(val)
            break
    for key in ("W_open", "open_width", "aperture_width", "w_open", "slot_open_width"):
        val = dims.get(key)
        if val is not None:
            info["W_open"] = str(val)
            break
    for key in ("L_slot", "slot_length", "length", "l_slot", "radiating_length"):
        val = dims.get(key)
        if val is not None:
            info["L_slot"] = str(val)
            break
    for key in ("R_taper", "taper_rate", "taper_coefficient", "r_taper"):
        val = dims.get(key)
        if val is not None:
            info["R_taper"] = str(val)
            break
    return info


def _build_hint_for_solid(solid: Dict[str, Any]) -> str:
    """Return a structured instruction block for one profile/polygon/cutout solid."""
    name = solid.get("name", "???")
    role = solid.get("Role", "")
    material = solid.get("material", "PEC")
    dims = solid.get("dimensions") or {}
    if not isinstance(dims, dict):
        dims = {}

    primitive = str(dims.get("primitive", "") or "").lower().strip()
    is_cutout = "cutout" in primitive or "cutout" in role.lower()
    effective_material = "Vacuum" if is_cutout else material

    height = str(
        dims.get("height")
        or dims.get("thickness")
        or dims.get("t")
        or dims.get("t_cu")
        or dims.get("t_sub")
        or "t_cu"
    )
    z_offset = str(
        dims.get("z_start")
        or dims.get("z_min")
        or dims.get("z_offset")
        or dims.get("Z_cu")
        or "0.0"
    )

    profile_def = dims.get("profile_definition") or dims.get("profile_points")
    taper_text = (
        str(dims.get("taper_type", "") or "")
        + str(dims.get("profile_type", "") or "")
        + str(dims.get("shape", "") or "")
        + str(dims.get("notes", "") or "")
    ).lower()
    is_tapered = any(kw in taper_text for kw in ("vivaldi", "taper", "ltsa"))

    lines: List[str] = []
    lines.append(f'[PROFILE SOLID: "{name}"]')
    lines.append(
        f"  Role={role!r} | primitive={primitive or 'polygon'} | material={effective_material!r}"
    )

    if is_cutout:
        lines.append(
            "  → Cutout body: use .Material \"Vacuum\".  "
            "Boolean subtraction is performed later in boolean_ops.bas."
        )

    # ---- Case A: explicit profile_definition --------------------------------
    if isinstance(profile_def, list) and len(profile_def) >= 3:
        lines.append(
            f"  → Use Extrude .Mode \"Pointlist\" with the {len(profile_def)} explicit points below."
        )
        lines.append(f'    .Height "{height}"  .Origin "0.0","0.0","{z_offset}"')
        lines.append("    Point coordinates (first uses .Point, rest use .LineTo, close polygon):")
        for i, pt in enumerate(profile_def):
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                verb = ".Point" if i == 0 else ".LineTo"
                lines.append(f"      {verb} \"{pt[0]}\", \"{pt[1]}\"")
        lines.append(
            f'    Final .LineTo must repeat the first point to close the polygon.'
        )

    # ---- Case B: tapered / Vivaldi slot -------------------------------------
    elif is_tapered:
        taper_params = _tapered_slot_info(dims)
        w_feed = taper_params.get("W_feed", "W_feed")
        w_open = taper_params.get("W_open", "W_open")
        l_slot = taper_params.get("L_slot", "L_slot")
        lines.append(
            "  → Exponential tapered slot (Vivaldi/LTSA). "
            "Use Extrude .Mode \"Pointlist\" from profile_cutout_extrude.md Pattern 3."
        )
        lines.append(
            f"    W_feed (narrow end) = {w_feed}  |  "
            f"W_open (aperture) = {w_open}  |  "
            f"L_slot = {l_slot}"
        )
        lines.append(
            f'    .Height "{height}"  .Origin "0.0","0.0","{z_offset}"'
        )
        lines.append(
            "    Right edge: ~8 .LineTo points with x growing exponentially from W_feed/2 to W_open/2."
        )
        lines.append(
            "    Top edge: straight from (W_open/2, L_slot) to (-W_open/2, L_slot)."
        )
        lines.append(
            "    Left edge: mirror of right edge (negate x), reversed order."
        )
        lines.append(
            "    Close polygon: final .LineTo back to (W_feed/2, 0)."
        )
        if taper_params:
            lines.append(
                "    Intermediate x-multipliers (for W_open/W_feed≈20) "
                "from profile_cutout_extrude.md Pattern 3: "
                "0.780, 1.215, 1.890, 2.950, 4.595, 7.150"
            )

    # ---- Case C: generic profile (no explicit points) -----------------------
    else:
        lines.append(
            "  → No explicit profile_definition. "
            "Infer polygon outline from dimension parameters and use Extrude .Mode \"Pointlist\"."
        )
        lines.append(f'    .Height "{height}"  .Origin "0.0","0.0","{z_offset}"')

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Description pre-processor
# ---------------------------------------------------------------------------

def _build_profile_context(description: Optional[str]) -> Optional[str]:
    """Scan the JSON description for profile/polygon/cutout solids.

    Returns an explicit instruction block to prepend to the LLM prompt, or
    None when no such solids are found or the description is not JSON.
    """
    if not description:
        return None

    parsed: Any = None
    try:
        parsed = json.loads(description)
    except (json.JSONDecodeError, TypeError):
        # Try to extract an embedded JSON object from free-form text
        m = re.search(r"\{.*\}", description, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group())
            except (json.JSONDecodeError, TypeError):
                pass

    if not isinstance(parsed, dict):
        return None

    solids: Any = (
        parsed.get("solids")
        or parsed.get("items")
        or parsed.get("elements")
        or []
    )
    if not isinstance(solids, list):
        return None

    profile_solids = [s for s in solids if isinstance(s, dict) and _is_profile_solid(s)]
    if not profile_solids:
        return None

    header = [
        "=== PROFILE / POLYGON / CUTOUT SOLIDS DETECTED ===",
        (
            "The following solids require profile-based VBA "
            "(Extrude Pointlist or Spline + ExtrudeCurve)."
        ),
        "Use the patterns in profile_cutout_extrude.md.",
        "",
    ]
    body: List[str] = []
    for solid in profile_solids:
        body.append(_build_hint_for_solid(solid))
        body.append("")

    footer = ["=== END PROFILE HINTS ==="]
    return "\n".join(header + body + footer)


# ---------------------------------------------------------------------------
# Generator class
# ---------------------------------------------------------------------------

class Model3DGenerator:
    """Generate 3D CST model VBA macros.

    Compared with the original generator this version also handles solids whose
    JSON description carries profile-based signals (primitive = polygon / profile /
    cutout, explicit profile_definition, tapered slot / Vivaldi keywords).  For
    each such solid a structured hint is injected into the LLM prompt so the model
    generates correct Extrude-Pointlist or ExtrudeCurve VBA instead of falling back
    to an inappropriate primitive.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        save_dir: Optional[str] = None,
    ):
        self.vba_generator = VBAGenerator(default_model=model)
        self.prompt_files = [
            prompt_path("modeling_3d_prompt.md"),
            resource_path("modeling_3d.md"),
            resource_path("modeling_2d.md"),
            resource_path("extrude_and_rotate.md"),
            resource_path("profile_cutout_extrude.md"),
        ]
        self.save_dir = resolve_save_dir(save_dir)

    def generate_model(
        self,
        description: Optional[str] = None,
        additional_prompt_files: Optional[List[str]] = None,
        save_as: str = "model_3d.bas",
    ) -> Optional[str]:
        """Generate a 3D CST model macro from a description.

        If the description contains profile/polygon/cutout solids (detected via
        JSON parsing), an explicit instruction block is appended so the LLM
        produces correct Extrude VBA for those shapes.
        """
        enriched_description = description
        profile_context = _build_profile_context(description)
        if profile_context:
            enriched_description = (description or "") + "\n\n" + profile_context

        prompt_files = self.prompt_files + (additional_prompt_files or [])
        return self.vba_generator.generate_vba(
            prompt_files=prompt_files,
            filename=os.path.join(self.save_dir, save_as),
            description=enriched_description,
            json_schema_hint=None,
            dimension_type="3d",
        )
