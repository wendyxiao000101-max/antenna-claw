from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]



def prompt_path(filename: str) -> str:
    """Return the absolute path to a prompt file."""
    return str(PACKAGE_ROOT / "prompts" / filename)



def resource_path(filename: str) -> str:
    """Return the absolute path to a resource file."""
    return str(PACKAGE_ROOT / "resources" / filename)
