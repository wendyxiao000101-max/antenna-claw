"""Validation and normalization for simulation configuration."""

from copy import deepcopy
from typing import Any, Dict, List, Tuple


VALID_BOUNDARY_VALUES = {
    "open": "Open",
    "open add space": "Open Add Space",
    "pml": "PML",
    "pec": "PEC",
    "pmc": "PMC",
    "symmetry": "Symmetry",
}

VALID_EXPORT_FORMATS = {"touchstone", "csv"}
VALID_SOLVER_TYPES = {"auto", "frequency_domain", "time_domain"}
UNIT_FACTORS_TO_GHZ = {
    "hz": 1e-9,
    "khz": 1e-6,
    "mhz": 1e-3,
    "ghz": 1.0,
}

DEFAULT_SIM_CONFIG: Dict[str, Any] = {
    "frequency": {"start": 2.0, "stop": 3.0, "unit": "GHz"},
    "boundary": {
        "xmin": "Open Add Space",
        "xmax": "Open Add Space",
        "ymin": "Open Add Space",
        "ymax": "Open Add Space",
        "zmin": "Open Add Space",
        "zmax": "Open Add Space",
    },
    "port": {"mode": "single", "reference_impedance": 50.0},
    "solver": {"type": "auto"},
    "export": {"s11": {"format": "touchstone"}},
}


class SimulationValidationService:
    """Validate and normalize LLM-produced simulation config."""

    def validate(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        config = deepcopy(DEFAULT_SIM_CONFIG)
        warnings: List[str] = []
        errors: List[Dict[str, str]] = []

        if not isinstance(raw, dict):
            raw = {}
            warnings.append("仿真配置不是对象，已回退默认配置。")

        self._validate_frequency(raw, config, warnings, errors)
        self._validate_boundary(raw, config, warnings)
        self._validate_port(raw, config, warnings)
        self._validate_solver(raw, config, warnings)
        self._validate_export(raw, config, warnings)

        return {
            "is_valid": len(errors) == 0,
            "config": config,
            "warnings": warnings,
            "errors": errors,
        }

    def _validate_frequency(
        self,
        raw: Dict[str, Any],
        config: Dict[str, Any],
        warnings: List[str],
        errors: List[Dict[str, str]],
    ) -> None:
        freq_raw = raw.get("frequency")
        if not isinstance(freq_raw, dict):
            warnings.append("未提供 frequency，使用默认 2.0-3.0 GHz。")
            return

        start, start_ok = self._to_float(freq_raw.get("start"))
        stop, stop_ok = self._to_float(freq_raw.get("stop"))
        unit_raw = str(freq_raw.get("unit") or "GHz").strip().lower()

        if unit_raw not in UNIT_FACTORS_TO_GHZ:
            warnings.append("frequency.unit 无效，已回退为 GHz。")
            unit_raw = "ghz"

        if start_ok and stop_ok:
            start_ghz = start * UNIT_FACTORS_TO_GHZ[unit_raw]
            stop_ghz = stop * UNIT_FACTORS_TO_GHZ[unit_raw]
            if start_ghz <= 0 or stop_ghz <= 0:
                errors.append(
                    {
                        "code": "INVALID_FREQUENCY_RANGE",
                        "message": "频率必须为正数。",
                        "suggestion": "请提供正数频率范围，例如 2.4-2.5 GHz。",
                    }
                )
                return
            if start_ghz >= stop_ghz:
                errors.append(
                    {
                        "code": "INVALID_FREQUENCY_ORDER",
                        "message": "frequency.start 必须小于 frequency.stop。",
                        "suggestion": "请调整频率范围顺序。",
                    }
                )
                return
            if stop_ghz > 200:
                warnings.append("频率上限较高，已保留但建议确认单位是否正确。")
            config["frequency"] = {
                "start": round(start_ghz, 6),
                "stop": round(stop_ghz, 6),
                "unit": "GHz",
            }
            return

        warnings.append("frequency.start/stop 缺失或无效，已使用默认值。")

    def _validate_boundary(
        self,
        raw: Dict[str, Any],
        config: Dict[str, Any],
        warnings: List[str],
    ) -> None:
        boundary_raw = raw.get("boundary")
        if not isinstance(boundary_raw, dict):
            return

        boundary = config["boundary"]
        for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"):
            val = boundary_raw.get(key)
            if val is None:
                continue
            norm = VALID_BOUNDARY_VALUES.get(str(val).strip().lower())
            if norm is None:
                warnings.append(f"boundary.{key}={val} 无效，已保留默认值 {boundary[key]}。")
                continue
            boundary[key] = norm

        tight_open_faces = [
            key
            for key in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
            if boundary[key] == "Open"
        ]
        if tight_open_faces:
            warnings.append(
                "检测到紧贴 Open 边界："
                + ", ".join(tight_open_faces)
                + "。天线/离散端口贴近包围盒时 CST 可能报 "
                + "'Distance between discrete port and open boundary is too small'，"
                + "如非刻意需求建议改用 'Open Add Space'。"
            )

    def _validate_port(
        self,
        raw: Dict[str, Any],
        config: Dict[str, Any],
        warnings: List[str],
    ) -> None:
        port_raw = raw.get("port")
        if not isinstance(port_raw, dict):
            return
        mode = str(port_raw.get("mode") or "single").strip().lower()
        if mode != "single":
            warnings.append("port.mode 当前仅支持 single，已回退 single。")
        config["port"]["mode"] = "single"

        z0, ok = self._to_float(port_raw.get("reference_impedance"))
        if ok and z0 > 0:
            config["port"]["reference_impedance"] = float(z0)
        elif port_raw.get("reference_impedance") is not None:
            warnings.append("port.reference_impedance 无效，已回退 50。")

    def _validate_solver(
        self,
        raw: Dict[str, Any],
        config: Dict[str, Any],
        warnings: List[str],
    ) -> None:
        solver_raw = raw.get("solver")
        if not isinstance(solver_raw, dict):
            return
        solver_type = str(solver_raw.get("type") or "auto").strip().lower()
        if solver_type not in VALID_SOLVER_TYPES:
            warnings.append("solver.type 无效，已回退 auto。")
            solver_type = "auto"
        config["solver"]["type"] = solver_type

    def _validate_export(
        self,
        raw: Dict[str, Any],
        config: Dict[str, Any],
        warnings: List[str],
    ) -> None:
        export_raw = raw.get("export")
        if not isinstance(export_raw, dict):
            return
        s11_raw = export_raw.get("s11")
        if not isinstance(s11_raw, dict):
            return
        fmt = str(s11_raw.get("format") or "touchstone").strip().lower()
        if fmt not in VALID_EXPORT_FORMATS:
            warnings.append("export.s11.format 无效，已回退 touchstone。")
            fmt = "touchstone"
        config["export"]["s11"]["format"] = fmt

    @staticmethod
    def _to_float(value: Any) -> Tuple[float, bool]:
        try:
            return float(value), True
        except Exception:
            return 0.0, False

    @staticmethod
    def format_summary(config: Dict[str, Any]) -> str:
        """Human-readable one-block summary of an effective simulation config."""
        freq = config.get("frequency", {}) or {}
        boundary = config.get("boundary", {}) or {}
        port = config.get("port", {}) or {}
        solver = config.get("solver", {}) or {}
        export = (config.get("export", {}) or {}).get("s11", {}) or {}

        start = freq.get("start", "?")
        stop = freq.get("stop", "?")
        unit = freq.get("unit", "GHz")

        face_order = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
        faces = [str(boundary.get(k, "?")) for k in face_order]
        if all(f == faces[0] for f in faces):
            boundary_line = f"\u8fb9\u754c 6\u9762 {faces[0]}"
        else:
            boundary_line = "\u8fb9\u754c " + " / ".join(
                f"{k}={v}" for k, v in zip(face_order, faces)
            )

        z0 = port.get("reference_impedance", 50.0)
        mode = port.get("mode", "single")
        solver_type = solver.get("type", "auto")
        s11_fmt = export.get("format", "touchstone")

        return (
            f"  \u9891\u7387 {start}-{stop} {unit} | {boundary_line} | "
            f"\u7aef\u53e3 {mode}@{z0}\u03a9 | solver={solver_type} | "
            f"S11={s11_fmt}"
        )
