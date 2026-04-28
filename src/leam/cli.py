import argparse
import os
from typing import List, Optional

from .config import (
    get_materials_path,
    get_python_libs_path,
    load_config,
    resolve_cst_path,
    resolve_openai_api_key,
    validate_cst_path,
)


def _print_status(label: str, ok: bool, detail: Optional[str] = None) -> None:
    status = "OK" if ok else "MISSING"
    if detail:
        print(f"{label}: {status} ({detail})")
    else:
        print(f"{label}: {status}")



def _doctor() -> int:
    config = load_config()
    openai_key = resolve_openai_api_key(config)
    cst_path = resolve_cst_path(config)
    overall_ok = True

    if openai_key:
        _print_status("OpenAI API key", True)
    else:
        _print_status("OpenAI API key", False)
        print(
            "Set LEAM_OPENAI_API_KEY or add openai_api_key to LEAM's local config.json."
        )
        overall_ok = False

    is_valid, message = validate_cst_path(cst_path)
    if is_valid and cst_path:
        _print_status("CST path", True, cst_path)
        materials_path = get_materials_path(cst_path)
        materials_ok = os.path.isdir(materials_path)
        _print_status("CST materials", materials_ok, materials_path)
        if not materials_ok:
            overall_ok = False

        python_libs = get_python_libs_path(cst_path)
        python_ok = os.path.isdir(python_libs)
        _print_status("CST python libs", python_ok, python_libs)
        if not python_ok:
            overall_ok = False
    else:
        _print_status("CST path", False)
        print(message)
        overall_ok = False

    return 0 if overall_ok else 1



def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="leam",
        description="LEAM utilities for configuration checks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check CST and OpenAI configuration.",
    )
    doctor_parser.set_defaults(func=_doctor)
    return parser



def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func()
