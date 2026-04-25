import os
import re
from typing import List, Optional

from ..core.vba_generator import VBAGenerator
from ..utils.constants import DEFAULT_MODEL
from ..utils.file_io import resolve_save_dir
from ..utils.paths import prompt_path, resource_path



class BooleanOperationsGenerator:
    """Generate VBA macros for boolean operations."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        save_dir: Optional[str] = None,
    ):
        self.vba_generator = VBAGenerator(default_model=model)
        self.prompt_files = [
            prompt_path("boolean_prompt.md"),
            resource_path("boolean_operations.md"),
        ]
        self.save_dir = resolve_save_dir(save_dir)

    def generate_operations(
        self,
        description: Optional[str] = None,
        additional_prompt_files: Optional[List[str]] = None,
        save_as: str = "boolean_ops.bas",
    ) -> Optional[str]:
        """Generate CST Boolean operations from a description."""
        prompt_files = self.prompt_files + (additional_prompt_files or [])
        filename = os.path.join(self.save_dir, save_as)
        code = self.vba_generator.generate_vba(
            prompt_files=prompt_files,
            filename=filename,
            description=description,
            json_schema_hint=None,
            dimension_type="3d",
        )

        # Remove explicit delete calls; subtraction tools are auto-deleted.
        if isinstance(code, str) and code.strip():
            filtered: List[str] = []
            for line in code.splitlines():
                if re.match(r"^\s*\.Delete\b", line, flags=re.IGNORECASE):
                    continue
                if re.search(r"\bSolid\.Delete\b", line, flags=re.IGNORECASE):
                    continue
                filtered.append(line)

            cleaned = "\n".join(filtered).strip() + "\n"
            if cleaned != (code.strip() + "\n"):
                code = cleaned
                try:
                    with open(filename, "w", encoding="utf-8") as output_file:
                        output_file.write(code)
                except Exception:
                    pass

        return code
