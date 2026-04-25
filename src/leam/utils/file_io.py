import os
from typing import Iterable, Optional

from .constants import DEFAULT_OUTPUT_DIR_NAME



def process_text_files(files: Iterable[str]) -> str:
    """Combine multiple text files into a single string."""
    contents = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                contents.append(f"{path}:\n{f.read()}")
        except Exception as e:
            print(f"Error reading {path}: {e}")
    return "\n\n".join(contents)



def resolve_save_dir(save_dir: Optional[str] = None) -> str:
    """
    Resolve and create the directory used for generated outputs.
    """
    target_dir = save_dir or os.path.join(os.getcwd(), DEFAULT_OUTPUT_DIR_NAME)
    os.makedirs(target_dir, exist_ok=True)
    return target_dir



def resolve_output_dir(save_dir: Optional[str] = None) -> str:
    """Alias for resolve_save_dir."""
    return resolve_save_dir(save_dir)
