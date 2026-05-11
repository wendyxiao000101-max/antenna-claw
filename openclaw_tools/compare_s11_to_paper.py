"""Compare LEAM S11 output against paper validation targets.

The script reads a PaperReplicationSpec JSON and a LEAM output directory,
extracts S11 metrics, writes paper_reproduction_report.json, and creates a
simple PNG preview when Pillow is available. It deliberately avoids heavy
scientific dependencies so it can run inside the LEAM .venv39 environment.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_PROJECT_ROOT = Path(r"D:\leam_openclaw_handoff")


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_s11_path(output_dir: Path) -> Optional[Path]:
    candidates = [
        output_dir / "results" / "sparams" / "s11.csv",
        output_dir / "results" / "sparams" / "s11.s1p",
        output_dir / "results" / "sparams" / "s11.s1p.s1p",
    ]
    for path in candidates:
        if path.exists():
            return path
    sparams = output_dir / "results" / "sparams"
    if sparams.exists():
        for pattern in ("*.csv", "*.s1p", "*.s1p.s1p"):
            found = sorted(sparams.glob(pattern))
            if found:
                return found[0]
    return None


def _parse_numeric_pair(line: str) -> Optional[Tuple[float, float]]:
    line = line.strip()
    if not line or line.startswith("!") or line.startswith("#"):
        return None
    tokens = re.split(r"[\s,;]+", line)
    numbers: List[float] = []
    for token in tokens:
        if not token:
            continue
        try:
            numbers.append(float(token))
        except ValueError:
            continue
    if len(numbers) < 2:
        return None
    return numbers[0], numbers[1]


def _read_touchstone(path: Path) -> List[Tuple[float, float]]:
    freq_unit = "ghz"
    data_format = "db"
    points: List[Tuple[float, float]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                parts = line.lower().split()
                if len(parts) > 1:
                    freq_unit = parts[1]
                if "db" in parts:
                    data_format = "db"
                elif "ma" in parts:
                    data_format = "ma"
                elif "ri" in parts:
                    data_format = "ri"
                continue
            pair = _parse_numeric_pair(line)
            if pair is None:
                continue
            freq, a = pair
            values = re.split(r"[\s,;]+", line)
            nums: List[float] = []
            for token in values:
                try:
                    nums.append(float(token))
                except ValueError:
                    pass
            b = nums[2] if len(nums) > 2 else 0.0
            freq_ghz = _freq_to_ghz(freq, freq_unit)
            if data_format == "db":
                s11_db = a
            elif data_format == "ma":
                s11_db = 20.0 * math.log10(max(abs(a), 1e-30))
            else:
                mag = math.sqrt(a * a + b * b)
                s11_db = 20.0 * math.log10(max(mag, 1e-30))
            points.append((freq_ghz, s11_db))
    return points


def _freq_to_ghz(value: float, unit: str) -> float:
    unit = unit.lower()
    factors = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0}
    return value * factors.get(unit, 1.0)


def _read_csv(path: Path) -> List[Tuple[float, float]]:
    text = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    sample = "\n".join(text[:5])
    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    points: List[Tuple[float, float]] = []

    for row in csv.reader(text, dialect):
        numeric = []
        for cell in row:
            try:
                numeric.append(float(str(cell).strip()))
            except ValueError:
                pass
        if len(numeric) < 2:
            continue
        freq = numeric[0]
        s11 = numeric[1]
        if freq > 1e5:
            freq = freq / 1e9
        points.append((freq, s11))
    return points


def read_s11(path: Path) -> List[Tuple[float, float]]:
    if path.suffix.lower() == ".csv":
        points = _read_csv(path)
    else:
        points = _read_touchstone(path)
    points = [(f, s) for f, s in points if math.isfinite(f) and math.isfinite(s)]
    points.sort(key=lambda item: item[0])
    return points


def _band_segments(points: Sequence[Tuple[float, float]], threshold_db: float) -> List[Dict[str, float]]:
    segments: List[Dict[str, float]] = []
    start: Optional[float] = None
    prev: Optional[float] = None
    for freq, s11 in points:
        if s11 <= threshold_db:
            if start is None:
                start = freq
            prev = freq
        elif start is not None and prev is not None:
            segments.append({"start_ghz": start, "stop_ghz": prev, "width_ghz": prev - start})
            start = None
            prev = None
    if start is not None and prev is not None:
        segments.append({"start_ghz": start, "stop_ghz": prev, "width_ghz": prev - start})
    return segments


def _extract_target(spec: Dict[str, Any]) -> Dict[str, Any]:
    raw = spec.get("validation_targets") or {}
    items = raw if isinstance(raw, list) else [raw]
    target: Dict[str, Any] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in (
            "resonance_frequency_ghz",
            "target_frequency_ghz",
            "center_frequency_ghz",
            "frequency_ghz",
            "min_s11_db",
            "threshold_db",
        ):
            if key in item and key not in target:
                target[key] = item[key]
        band = item.get("minus_10db_band_ghz") or item.get("band_ghz")
        if band is not None and "minus_10db_band_ghz" not in target:
            target["minus_10db_band_ghz"] = band
    return target


def _target_band(target: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    band = target.get("minus_10db_band_ghz")
    if isinstance(band, dict):
        start = _to_float(band.get("start") or band.get("lo"))
        stop = _to_float(band.get("stop") or band.get("hi"))
    elif isinstance(band, list) and len(band) >= 2:
        start = _to_float(band[0])
        stop = _to_float(band[1])
    else:
        return None
    if start is None or stop is None:
        return None
    return (min(start, stop), max(start, stop))


def _covers_band(segments: Sequence[Dict[str, float]], band: Tuple[float, float]) -> bool:
    lo, hi = band
    for seg in segments:
        if seg["start_ghz"] <= lo and seg["stop_ghz"] >= hi:
            return True
    return False


def build_report(
    *,
    spec: Dict[str, Any],
    output_dir: Path,
    s11_path: Path,
    points: Sequence[Tuple[float, float]],
    resonance_tolerance: float,
) -> Dict[str, Any]:
    if not points:
        raise ValueError("No S11 points could be parsed.")
    min_freq, min_s11 = min(points, key=lambda item: item[1])
    segments = _band_segments(points, -10.0)
    target = _extract_target(spec)
    target_freq = (
        _to_float(target.get("resonance_frequency_ghz"))
        or _to_float(target.get("target_frequency_ghz"))
        or _to_float(target.get("center_frequency_ghz"))
        or _to_float(target.get("frequency_ghz"))
    )
    target_min_s11 = _to_float(target.get("min_s11_db") or target.get("threshold_db"))
    target_band = _target_band(target)

    checks: Dict[str, Any] = {}
    if target_freq:
        error_pct = abs(min_freq - target_freq) / target_freq * 100.0
        checks["resonance_frequency"] = {
            "target_ghz": target_freq,
            "simulated_ghz": min_freq,
            "error_percent": error_pct,
            "pass": error_pct <= resonance_tolerance,
        }
    if target_min_s11 is not None:
        checks["minimum_s11"] = {
            "target_db": target_min_s11,
            "simulated_db": min_s11,
            "pass": min_s11 <= target_min_s11,
        }
    if target_band:
        checks["minus_10db_band"] = {
            "target_start_ghz": target_band[0],
            "target_stop_ghz": target_band[1],
            "simulated_segments": list(segments),
            "pass": _covers_band(segments, target_band),
        }

    if checks:
        passed = all(bool(item.get("pass")) for item in checks.values())
    else:
        passed = False

    return {
        "schema_version": "1.0",
        "output_dir": str(output_dir),
        "s11_path": str(s11_path),
        "metrics": {
            "minimum_s11_db": min_s11,
            "resonance_frequency_ghz": min_freq,
            "minus_10db_segments": list(segments),
            "point_count": len(points),
        },
        "paper_targets": target,
        "checks": checks,
        "verdict": "match" if passed else "deviates_or_incomplete",
        "notes": (
            "Pass means S11 resonance and available paper targets meet the configured thresholds. "
            "Missing paper targets produce an incomplete verdict."
        ),
    }


def _map_point(
    freq: float,
    s11: float,
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    width: int,
    height: int,
    pad: int,
) -> Tuple[int, int]:
    x = pad + int((freq - x_min) / max(x_max - x_min, 1e-12) * (width - 2 * pad))
    y = pad + int((y_max - s11) / max(y_max - y_min, 1e-12) * (height - 2 * pad))
    return x, y


def write_png(points: Sequence[Tuple[float, float]], path: Path, report: Dict[str, Any]) -> Optional[Path]:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    width, height, pad = 900, 520, 60
    x_min = min(freq for freq, _ in points)
    x_max = max(freq for freq, _ in points)
    y_min = min(-40.0, min(s11 for _, s11 in points) - 3.0)
    y_max = max(0.0, max(s11 for _, s11 in points) + 3.0)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((pad, pad, width - pad, height - pad), outline=(40, 40, 40))

    for level in (0, -10, -20, -30):
        if y_min <= level <= y_max:
            _, y = _map_point(
                x_min,
                level,
                x_min=x_min,
                x_max=x_max,
                y_min=y_min,
                y_max=y_max,
                width=width,
                height=height,
                pad=pad,
            )
            color = (200, 60, 60) if level == -10 else (220, 220, 220)
            draw.line((pad, y, width - pad, y), fill=color, width=1)
            draw.text((8, y - 7), f"{level} dB", fill=(80, 80, 80))

    mapped = [
        _map_point(
            f,
            s,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            width=width,
            height=height,
            pad=pad,
        )
        for f, s in points
    ]
    if len(mapped) >= 2:
        draw.line(mapped, fill=(20, 90, 180), width=2)

    metrics = report["metrics"]
    title = (
        f"S11: min {metrics['minimum_s11_db']:.2f} dB "
        f"at {metrics['resonance_frequency_ghz']:.4g} GHz"
    )
    draw.text((pad, 20), title, fill=(20, 20, 20))
    draw.text((pad, height - 35), f"Frequency GHz: {x_min:.4g} - {x_max:.4g}", fill=(20, 20, 20))
    draw.text((width - 230, height - 35), "S11 dB", fill=(20, 20, 20))

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path, help="PaperReplicationSpec JSON path.")
    parser.add_argument("--output-dir", type=Path, default=None, help="LEAM output directory.")
    parser.add_argument("--output-name", default=None, help="LEAM output_name under examples/output.")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--s11", type=Path, default=None, help="Explicit S11 CSV/Touchstone path.")
    parser.add_argument("--resonance-tolerance-percent", type=float, default=5.0)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--png", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    spec = _load_json(args.spec)
    if args.output_dir:
        output_dir = args.output_dir.resolve()
    elif args.output_name:
        output_dir = args.project_root.resolve() / "examples" / "output" / args.output_name
    elif spec.get("output_name"):
        output_dir = args.project_root.resolve() / "examples" / "output" / str(spec["output_name"])
    else:
        raise ValueError("Provide --output-dir, --output-name, or spec.output_name.")

    s11_path = args.s11.resolve() if args.s11 else _find_s11_path(output_dir)
    if s11_path is None:
        raise FileNotFoundError(f"No S11 CSV/Touchstone found under {output_dir}")

    points = read_s11(s11_path)
    report = build_report(
        spec=spec,
        output_dir=output_dir,
        s11_path=s11_path,
        points=points,
        resonance_tolerance=args.resonance_tolerance_percent,
    )

    report_path = args.report_json or output_dir / "results" / "paper_reproduction_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    png_path = args.png or output_dir / "results" / "paper_reproduction_s11.png"
    rendered = write_png(points, png_path, report)
    if rendered:
        report["plot_png"] = str(rendered)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
