import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from leam.tools import CstRunner

session_name = "cli_patch_cst"
output_dir = PROJECT_ROOT / "examples" / "output" / session_name
output_dir.mkdir(parents=True, exist_ok=True)

runner = CstRunner(create_new_if_none=False)

vba_tasks = {
    "Parameters": str(output_dir / "cli_patch_cst_parameters.bas"),
    "Materials": str(output_dir / "cli_patch_cst_materials.bas"),
    "3D Model": str(output_dir / "cli_patch_cst_model.bas"),
    "Boolean Operations": str(output_dir / "cli_patch_cst_boolean.bas"),
}

runner.set_history_tasks(vba_tasks)
runner.create_project(str(output_dir / "cli_patch_cst.cst"))