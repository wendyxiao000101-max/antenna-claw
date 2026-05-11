"""OpenClaw wrapper for reproducing antenna papers with LEAM.

Input is a PaperReplicationSpec JSON produced by OpenClaw after reading a
paper. This script converts that structured spec into the current LEAM
BuildAndSimulateRequest API. It intentionally does not add a new LEAM API.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_PROJECT_ROOT = Path(r"D:\leam_openclaw_handoff")


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("PaperReplicationSpec must be a JSON object.")
    return payload


def _slug(text: str, fallback: str = "paper_replication") -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_\-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80] or fallback


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _stringify_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _format_kv_block(title: str, value: Any) -> List[str]:
    lines: List[str] = [f"{title}:"]
    if not value:
        lines.append("- not specified")
        return lines
    if isinstance(value, dict):
        for key, item in value.items():
            lines.append(f"- {key}: {_stringify_value(item)}")
        return lines
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                label = item.get("name") or item.get("id") or item.get("role") or "item"
                detail = {
                    key: val
                    for key, val in item.items()
                    if key not in {"name", "id", "role"}
                }
                lines.append(f"- {label}: {_stringify_value(detail)}")
            else:
                lines.append(f"- {_stringify_value(item)}")
        return lines
    lines.append(f"- {_stringify_value(value)}")
    return lines


def build_description(spec: Dict[str, Any]) -> str:
    """Build a strong, constraint-heavy LEAM description from paper data."""
    paper_meta = spec.get("paper_meta") or {}
    title = paper_meta.get("title") or spec.get("title") or "unknown paper"
    antenna_type = paper_meta.get("antenna_type") or spec.get("antenna_type") or ""
    application = paper_meta.get("target_application") or paper_meta.get("application") or ""

    lines: List[str] = [
        "Reproduce the antenna design from a published paper in CST.",
        f"Paper title: {title}",
    ]
    if antenna_type:
        lines.append(f"Antenna type: {antenna_type}")
    if application:
        lines.append(f"Target application: {application}")

    lines.extend(
        [
            "",
            "Hard requirements:",
            "- Use the paper-provided topology, dimensions, materials, feed, and coordinate datum.",
            "- Prefer parametric dimensions with the same parameter names as the paper when possible.",
            "- Do not invent decorative or unsupported structures.",
            "- If a value is missing, keep a named parameter and document the assumption in notes.",
            "- Include the feed/port geometry needed for CST S11 simulation.",
            "- Use millimeters for length parameters unless the paper explicitly uses another unit.",
            "",
        ]
    )

    for title_key, spec_key in [
        ("Topology", "topology"),
        ("Parameters", "parameters"),
        ("Materials", "materials"),
        ("Port and feed", "port"),
        ("Simulation setup from paper", "simulation"),
        ("Validation targets from paper", "validation_targets"),
        ("Additional notes", "notes"),
    ]:
        lines.extend(_format_kv_block(title_key, spec.get(spec_key)))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _freq_range_from_targets(targets: Any) -> Optional[tuple]:
    candidates = _as_list(targets)
    freqs: List[float] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        for key in (
            "resonance_frequency_ghz",
            "target_frequency_ghz",
            "center_frequency_ghz",
            "frequency_ghz",
        ):
            try:
                if item.get(key) is not None:
                    freqs.append(float(item[key]))
            except (TypeError, ValueError):
                pass
        band = item.get("minus_10db_band_ghz") or item.get("band_ghz")
        if isinstance(band, dict):
            try:
                freqs.extend([float(band["start"]), float(band["stop"])])
            except (KeyError, TypeError, ValueError):
                pass
        elif isinstance(band, list) and len(band) >= 2:
            try:
                freqs.extend([float(band[0]), float(band[1])])
            except (TypeError, ValueError):
                pass
    if not freqs:
        return None
    lo = min(freqs)
    hi = max(freqs)
    if lo == hi:
        margin = max(0.5, lo * 0.25)
        return max(0.01, lo - margin), lo + margin
    span = hi - lo
    margin = max(0.2, span * 0.5)
    return max(0.01, lo - margin), hi + margin


def build_simulation_request(spec: Dict[str, Any]) -> str:
    simulation = spec.get("simulation") or {}
    if isinstance(simulation, str) and simulation.strip():
        return simulation.strip()

    parts: List[str] = []
    freq = simulation.get("frequency") if isinstance(simulation, dict) else None
    if isinstance(freq, dict) and freq.get("start") and freq.get("stop"):
        unit = freq.get("unit") or "GHz"
        parts.append(f"{freq['start']}-{freq['stop']} {unit}")
    else:
        inferred = _freq_range_from_targets(spec.get("validation_targets"))
        if inferred:
            parts.append(f"{inferred[0]:.6g}-{inferred[1]:.6g} GHz")
        else:
            parts.append("2.0-3.0 GHz")

    boundary = simulation.get("boundary") if isinstance(simulation, dict) else None
    if boundary:
        parts.append(_stringify_value(boundary))
    else:
        parts.append("Open Add Space")

    port = spec.get("port") or {}
    z0 = None
    if isinstance(port, dict):
        z0 = port.get("reference_impedance") or port.get("reference_impedance_ohm")
    parts.append(f"{z0 or 50} Ohm")
    parts.append("export S11 touchstone")
    return ", ".join(parts)


def _default_output_name(spec: Dict[str, Any], spec_path: Path) -> str:
    explicit = spec.get("output_name")
    if explicit:
        return _slug(str(explicit))
    paper_meta = spec.get("paper_meta") or {}
    title = paper_meta.get("title") or spec_path.stem
    return _slug(f"paper_{title}")


def _summarize_generated(paths: Dict[str, str]) -> Dict[str, bool]:
    return {name: Path(path).exists() for name, path in paths.items()}


def run_leam(
    *,
    spec: Dict[str, Any],
    spec_path: Path,
    project_root: Path,
    mode: str,
    output_name: Optional[str],
    enable_topology_check: bool,
) -> Dict[str, Any]:
    sys.path.insert(0, str(project_root))
    from leam import BuildAndSimulateRequest, LeamService

    name = _slug(output_name) if output_name else _default_output_name(spec, spec_path)
    description = build_description(spec)
    simulation_request = build_simulation_request(spec)

    if mode == "build-only":
        request = BuildAndSimulateRequest(
            description=description,
            output_name=name,
            design_mode="strong",
            execution_mode="build_only",
            simulation_request="",
            run_cst=False,
            prefer_template=False,
            enable_topology_check=enable_topology_check,
        )
    elif mode == "simulate":
        request = BuildAndSimulateRequest(
            description=description,
            output_name=name,
            design_mode="strong",
            execution_mode="simulate_and_export",
            simulation_request=simulation_request,
            run_cst=True,
            prefer_template=False,
            enable_topology_check=enable_topology_check,
        )
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    result = LeamService(project_root=project_root).build_and_simulate(request)
    payload = result.to_dict()
    payload["paper_replication"] = {
        "spec_path": str(spec_path),
        "mode": mode,
        "description": description,
        "simulation_request": simulation_request,
        "generated_exists": _summarize_generated(payload.get("paths", {})),
    }
    return payload


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path, help="PaperReplicationSpec JSON path.")
    parser.add_argument(
        "--mode",
        choices=("build-only", "simulate"),
        default="build-only",
        help="Run build-only first; use simulate only after user confirmation.",
    )
    parser.add_argument("--output-name", default=None, help="Override LEAM output_name.")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument(
        "--disable-topology-check",
        action="store_true",
        help="Disable LEAM topology auto-check/revision pass.",
    )
    parser.add_argument(
        "--result-json",
        type=Path,
        default=None,
        help="Optional path for wrapper result JSON.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    spec_path = args.spec.resolve()
    spec = _load_json(spec_path)
    result = run_leam(
        spec=spec,
        spec_path=spec_path,
        project_root=args.project_root.resolve(),
        mode=args.mode,
        output_name=args.output_name,
        enable_topology_check=not args.disable_topology_check,
    )

    if args.result_json:
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
