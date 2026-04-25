import json
import os
import platform
import sys
from typing import Dict, Optional, Tuple

CONFIG_FILE = "config.json"
ENV_CST_PATH = "CST_PATH"
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"


def load_config(config_file: str = CONFIG_FILE) -> Dict:
    """Load configuration from disk."""
    if os.path.exists(config_file):
        with open(config_file, "r", encoding="utf-8") as file:
            return json.load(file)
    return {}


def save_config(config: Dict, config_file: str = CONFIG_FILE) -> None:
    """Persist configuration to disk."""
    with open(config_file, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=4)


def resolve_cst_path(config: Dict) -> Optional[str]:
    """Resolve CST path from config or environment."""
    return config.get("cst_path") or os.environ.get(ENV_CST_PATH)


def resolve_openai_api_key(config: Dict) -> Optional[str]:
    """Resolve OpenAI API key from environment or config."""
    return os.environ.get(ENV_OPENAI_API_KEY) or config.get("openai_api_key")


def ensure_openai_api_key(config_file: str = CONFIG_FILE) -> str:
    """Ensure an OpenAI API key is configured."""
    config = load_config(config_file)
    api_key = resolve_openai_api_key(config)
    if not api_key:
        raise RuntimeError(
            "OpenAI API key not configured. Set OPENAI_API_KEY or add "
            "openai_api_key to config.json."
        )
    os.environ.setdefault(ENV_OPENAI_API_KEY, api_key)
    return api_key


def get_materials_path(cst_path: str) -> str:
    """Return the CST materials library path."""
    return os.path.join(cst_path, "Library", "Materials")


def get_python_libs_path(cst_path: str) -> str:
    if platform.system() == "Windows":
        return os.path.join(cst_path, "AMD64", "python_cst_libraries")
    return os.path.join(cst_path, "LinuxAMD64", "python_cst_libraries")


def _ensure_pythonpath(python_libs: str) -> None:
    current_pythonpath = os.environ.get("PYTHONPATH", "")
    if python_libs not in current_pythonpath:
        if current_pythonpath:
            new_pythonpath = f"{current_pythonpath}{os.pathsep}{python_libs}"
        else:
            new_pythonpath = python_libs
        os.environ["PYTHONPATH"] = new_pythonpath
    if python_libs not in sys.path:
        sys.path.append(python_libs)


def validate_cst_path(cst_path: Optional[str]) -> Tuple[bool, str]:
    """Validate the CST path and return a status with details."""
    if not cst_path:
        return (
            False,
            "CST path not configured. Set CST_PATH or add cst_path to "
            "config.json.",
        )
    if not os.path.isdir(cst_path):
        return False, f"CST path not found: {cst_path}"
    return True, ""


def get_paths(config_file: str = CONFIG_FILE) -> Tuple[str, str, str]:
    """
    Get and persist CST-related paths.

    Returns:
        (cst_path, material_library_path, python_libraries_path)
    """
    config = load_config(config_file)
    cst_path = resolve_cst_path(config)
    if not cst_path:
        raise RuntimeError(
            "CST path not configured. Set CST_PATH or add cst_path to config.json."
        )

    is_valid, message = validate_cst_path(cst_path)
    if not is_valid:
        raise ValueError(message)

    material_path = get_materials_path(cst_path)
    python_libs = get_python_libs_path(cst_path)

    config["cst_path"] = cst_path
    config["material_library_path"] = material_path
    config["python_libraries_path"] = python_libs
    save_config(config, config_file)

    _ensure_pythonpath(python_libs)

    return cst_path, material_path, python_libs
