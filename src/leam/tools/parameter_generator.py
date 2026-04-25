import os
from typing import List, Optional

from ..core.vba_generator import VBAGenerator
from ..utils.constants import DEFAULT_MODEL
from ..utils.file_io import resolve_save_dir
from ..utils.paths import prompt_path



class ParameterGenerator:
    """Generate CST parameter VBA macros from descriptions."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        save_dir: Optional[str] = None,
    ):
        self.vba_generator = VBAGenerator(default_model=model)
        self.default_prompt_file = prompt_path("parameter_prompt.md")
        self.save_dir = resolve_save_dir(save_dir)

    def generate_parameters(
        self,
        description: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        output_file: str = "parameters.bas",
        prompt_file: Optional[str] = None,
    ) -> Optional[str]:
        """Generate CST parameters from descriptions and optional images."""
        prompt_files = [self.default_prompt_file]
        if prompt_file and os.path.exists(prompt_file):
            prompt_files.append(prompt_file)

        return self.vba_generator.generate_vba(
            prompt_files=prompt_files,
            filename=os.path.join(self.save_dir, output_file),
            description=description,
            image_paths=image_paths,
        )
