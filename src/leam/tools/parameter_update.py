import os
from typing import List, Optional

from ..core.vba_generator import VBAGenerator
from ..utils.constants import DEFAULT_MODEL
from ..utils.file_io import resolve_save_dir
from ..utils.paths import prompt_path



class ParameterUpdater:
    """Generate VBA macros that update CST parameters."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        save_dir: Optional[str] = None,
    ):
        self.vba_generator = VBAGenerator(default_model=model)
        self.parameter_prompt = prompt_path("parameter_update_prompt.md")
        self.save_dir = resolve_save_dir(save_dir)

    def generate_update(
        self,
        description: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        additional_prompt_files: Optional[List[str]] = None,
        save_as: str = "parameter_update.bas",
    ) -> Optional[str]:
        """Generate VBA code for parameter updates."""
        prompt_files = [self.parameter_prompt]
        if additional_prompt_files:
            prompt_files.extend(additional_prompt_files)

        return self.vba_generator.generate_vba(
            prompt_files=prompt_files,
            filename=os.path.join(self.save_dir, save_as),
            image_paths=image_paths,
            description=description,
            json_schema_hint=None,
            dimension_type=None,
        )
