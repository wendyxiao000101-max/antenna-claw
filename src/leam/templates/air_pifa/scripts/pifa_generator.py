"""Deterministic VBA / JSON file generator for the air-substrate PIFA.

Every output is produced from hard-coded string templates that mirror the
validated CST history list.  **No LLM calls.**  Only the numeric values
inside ``StoreParameters`` change; all geometric expressions use CST
parameter names (``"Lp/2"``, ``"t_cu+h+t_cu"``, etc.).
"""

import json
from pathlib import Path
from typing import Dict, List

# ── solids JSON ──────────────────────────────────────────────────────

_SOLIDS_TEMPLATE = [
    {
        "name": "GroundPlane",
        "shape": "Brick",
        "component": "component1",
        "material": "Copper (annealed)",
        "role": "Ground plane",
    },
    {
        "name": "RadiatingPatch",
        "shape": "Brick",
        "component": "component1",
        "material": "Copper (annealed)",
        "role": "Radiating patch",
    },
    {
        "name": "ShortingPin",
        "shape": "Cylinder",
        "component": "component1",
        "material": "Copper (annealed)",
        "role": "Shorting pin connecting patch to ground",
    },
    {
        "name": "FeedPin_Bottom",
        "shape": "Cylinder",
        "component": "component1",
        "material": "Copper (annealed)",
        "role": "Feed pin lower segment (ground side)",
    },
    {
        "name": "FeedPin_Top",
        "shape": "Cylinder",
        "component": "component1",
        "material": "Copper (annealed)",
        "role": "Feed pin upper segment (patch side)",
    },
    {
        "name": "FeedPort_Gap",
        "shape": "Cylinder",
        "component": "component1",
        "material": "Vacuum",
        "role": "Discrete-port gap between feed-pin segments",
    },
]


def _generate_solids_json(params: Dict) -> str:
    doc = {
        "antenna_type": "PIFA",
        "substrate": "air",
        "template": "air_pifa_v1",
        "parameters": {k: round(v, 6) for k, v in params.items()},
        "solids": _SOLIDS_TEMPLATE,
    }
    return json.dumps(doc, indent=2, ensure_ascii=False)


# ── dimensions JSON ──────────────────────────────────────────────────

def _generate_dimensions_json(params: Dict) -> str:
    doc = {
        "unit": "mm",
        "parameters": {k: round(v, 6) for k, v in params.items()},
        "solids": [
            {
                "name": "GroundPlane",
                "shape": "Brick",
                "material": "Copper (annealed)",
                "dimensions": {
                    "Xmin": "-Lg/2", "Xmax": "Lg/2",
                    "Ymin": "-Wg/2", "Ymax": "Wg/2",
                    "Zmin": "0", "Zmax": "t_cu",
                },
            },
            {
                "name": "RadiatingPatch",
                "shape": "Brick",
                "material": "Copper (annealed)",
                "dimensions": {
                    "Xmin": "-Lp/2", "Xmax": "Lp/2",
                    "Ymin": "-Wp/2", "Ymax": "Wp/2",
                    "Zmin": "t_cu+h", "Zmax": "t_cu+h+t_cu",
                },
            },
            {
                "name": "ShortingPin",
                "shape": "Cylinder",
                "material": "Copper (annealed)",
                "dimensions": {
                    "OuterRadius": "dPin/2",
                    "Axis": "z",
                    "Zmin": "0", "Zmax": "t_cu+h+t_cu",
                    "Xcenter": "-Lp/2 + dPin/2", "Ycenter": "0",
                },
            },
            {
                "name": "FeedPin_Bottom",
                "shape": "Cylinder",
                "material": "Copper (annealed)",
                "dimensions": {
                    "OuterRadius": "dPin/2",
                    "Axis": "z",
                    "Zmin": "0", "Zmax": "t_cu+h-gPort",
                    "Xcenter": "-Lp/2 + dPin/2", "Ycenter": "sPins",
                },
            },
            {
                "name": "FeedPin_Top",
                "shape": "Cylinder",
                "material": "Copper (annealed)",
                "dimensions": {
                    "OuterRadius": "dPin/2",
                    "Axis": "z",
                    "Zmin": "t_cu+h", "Zmax": "t_cu+h+t_cu",
                    "Xcenter": "-Lp/2 + dPin/2", "Ycenter": "sPins",
                },
            },
            {
                "name": "FeedPort_Gap",
                "shape": "Cylinder",
                "material": "Vacuum",
                "dimensions": {
                    "OuterRadius": "dPin/2",
                    "Axis": "z",
                    "Zmin": "t_cu+h-gPort", "Zmax": "t_cu+h",
                    "Xcenter": "-Lp/2 + dPin/2", "Ycenter": "sPins",
                },
            },
        ],
        "boolean_operations": [
            {"op": "Add", "target": "component1:GroundPlane", "tool": "component1:ShortingPin"},
            {"op": "Add", "target": "component1:GroundPlane", "tool": "component1:FeedPin_Bottom"},
            {"op": "Add", "target": "component1:RadiatingPatch", "tool": "component1:FeedPin_Top"},
        ],
        "port": {
            "type": "DiscretePort",
            "impedance_ohm": 50.0,
            "P1": "(-Lp/2, sPins, t_cu+h-gPort)",
            "P2": "(-Lp/2, sPins, t_cu+h)",
        },
    }
    return json.dumps(doc, indent=2, ensure_ascii=False)


# ── parameters VBA ───────────────────────────────────────────────────

_PARAM_ORDER = [
    ("t_cu",  "Copper thickness (ground/patch)"),
    ("Lg",    "Ground plane length (X)"),
    ("Wg",    "Ground plane width (Y)"),
    ("h",     "Height between ground top and patch bottom"),
    ("Lp",    "Radiating patch length (X)"),
    ("Wp",    "Radiating patch width (Y)"),
    ("dPin",  "Short/feed pin diameter"),
    ("sPins", "Y-offset spacing between shorting pin and feed pin centers"),
    ("gPort", "Discrete port gap (Z)"),
]


def _generate_parameters_bas(params: Dict) -> str:
    n = len(_PARAM_ORDER)
    lines = [
        f"Dim names(1 To {n}) As String",
        f"Dim values(1 To {n}) As String",
        "",
    ]
    for idx, (name, comment) in enumerate(_PARAM_ORDER, 1):
        val = params[name]
        lines.append(f'names({idx}) = "{name}"   \' {comment}')
        lines.append(f'values({idx}) = "{val}"')
        lines.append("")
    lines.append("StoreParameters names, values")
    return "\n".join(lines)


# ── materials VBA (fixed) ────────────────────────────────────────────

_MATERIALS_BAS = """\
With Material
    .Reset
    .Name "Copper (annealed)"
    .FrqType "static"
    .Type "Normal"
    .SetMaterialUnit "Hz", "mm"
    .Epsilon "1"
    .Mu "1.0"
    .Kappa "5.8e+007"
    .TanD "0.0"
    .TanDFreq "0.0"
    .TanDGiven "False"
    .TanDModel "ConstTanD"
    .KappaM "0"
    .TanDM "0.0"
    .TanDMFreq "0.0"
    .TanDMGiven "False"
    .TanDMModel "ConstTanD"
    .DispModelEps "None"
    .DispModelMu "None"
    .DispersiveFittingSchemeEps "Nth Order"
    .DispersiveFittingSchemeMu "Nth Order"
    .UseGeneralDispersionEps "False"
    .UseGeneralDispersionMu "False"
    .FrqType "all"
    .Type "Lossy metal"
    .SetMaterialUnit "GHz", "mm"
    .Mu "1.0"
    .Kappa "5.8e+007"
    .Rho "8930.0"
    .ThermalType "Normal"
    .ThermalConductivity "401.0"
    .SpecificHeat "390", "J/K/kg"
    .MetabolicRate "0"
    .BloodFlow "0"
    .VoxelConvection "0"
    .MechanicsType "Isotropic"
    .YoungsModulus "120"
    .PoissonsRatio "0.33"
    .ThermalExpansionRate "17"
    .Colour "1", "1", "0"
    .Wireframe "False"
    .Reflection "False"
    .Allowoutline "True"
    .Transparentoutline "False"
    .Transparency "0"
    .Create
End With
"""


# ── 3-D model VBA ────────────────────────────────────────────────────

_MODEL_BAS = """\
With Brick
     .Reset
     .Name "GroundPlane"
     .Component "component1"
     .Material "Copper (annealed)"
     .Xrange "-Lg/2", "Lg/2"
     .Yrange "-Wg/2", "Wg/2"
     .Zrange "0", "t_cu"
     .Create
End With

With Brick
     .Reset
     .Name "RadiatingPatch"
     .Component "component1"
     .Material "Copper (annealed)"
     .Xrange "-Lp/2", "Lp/2"
     .Yrange "-Wp/2", "Wp/2"
     .Zrange "t_cu+h", "t_cu+h+t_cu"
     .Create
End With

With Cylinder
     .Reset
     .Name "ShortingPin"
     .Component "component1"
     .Material "Copper (annealed)"
     .OuterRadius "dPin/2"
     .InnerRadius "0"
     .Axis "z"
     .Zrange "0", "t_cu+h+t_cu"
     .Xcenter "-Lp/2 + dPin/2"
     .Ycenter "0"
     .Segments "0"
     .Create
End With

With Cylinder
     .Reset
     .Name "FeedPin_Bottom"
     .Component "component1"
     .Material "Copper (annealed)"
     .OuterRadius "dPin/2"
     .InnerRadius "0"
     .Axis "z"
     .Zrange "0", "t_cu+h-gPort"
     .Xcenter "-Lp/2 + dPin/2"
     .Ycenter "sPins"
     .Segments "0"
     .Create
End With

With Cylinder
     .Reset
     .Name "FeedPin_Top"
     .Component "component1"
     .Material "Copper (annealed)"
     .OuterRadius "dPin/2"
     .InnerRadius "0"
     .Axis "z"
     .Zrange "t_cu+h", "t_cu+h+t_cu"
     .Xcenter "-Lp/2 + dPin/2"
     .Ycenter "sPins"
     .Segments "0"
     .Create
End With

With Cylinder
     .Reset
     .Name "FeedPort_Gap"
     .Component "component1"
     .Material "Vacuum"
     .OuterRadius "dPin/2"
     .InnerRadius "0"
     .Axis "z"
     .Zrange "t_cu+h-gPort", "t_cu+h"
     .Xcenter "-Lp/2 + dPin/2"
     .Ycenter "sPins"
     .Segments "0"
     .Create
End With
"""


# ── boolean + port VBA ───────────────────────────────────────────────

_BOOLEAN_BAS = """\
With Solid
    .Add "component1:GroundPlane", "component1:ShortingPin"
    .Add "component1:GroundPlane", "component1:FeedPin_Bottom"
    .Add "component1:RadiatingPatch", "component1:FeedPin_Top"
End With

Pick.PickMidpointFromId "component1:FeedPort_Gap", "1"

Pick.PickMidpointFromId "component1:FeedPort_Gap", "2"

With DiscretePort
     .Reset
     .PortNumber "1"
     .Type "SParameter"
     .Label ""
     .Folder ""
     .Impedance "50.0"
     .Voltage "1.0"
     .Current "1.0"
     .Monitor "True"
     .Radius "0.0"
     .SetP1 "True", "-Lp/2", "sPins", "t_cu+h-gPort"
     .SetP2 "True", "-Lp/2", "sPins", "t_cu+h"
     .InvertDirection "False"
     .LocalCoordinates "False"
     .Wire ""
     .Position "end1"
     .Create
End With
"""


# ── public API ───────────────────────────────────────────────────────

def generate_all(
    params: Dict,
    output_dir: Path,
    output_name: str,
) -> List[Path]:
    """Write all 6 output files and return their paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files: List[Path] = []

    def _write(filename: str, content: str) -> Path:
        p = output_dir / filename
        p.write_text(content, encoding="utf-8")
        files.append(p)
        return p

    _write(f"{output_name}.json", _generate_solids_json(params))
    _write(f"{output_name}_parameters.bas", _generate_parameters_bas(params))
    _write(f"{output_name}_dimensions.json", _generate_dimensions_json(params))
    _write(f"{output_name}_materials.bas", _MATERIALS_BAS)
    _write(f"{output_name}_model.bas", _MODEL_BAS)
    _write(f"{output_name}_boolean.bas", _BOOLEAN_BAS)

    return files
