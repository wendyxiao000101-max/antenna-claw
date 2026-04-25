import os
from typing import List, Optional

from ..core.vba_generator import VBAGenerator
from ..utils.constants import DEFAULT_MODEL
from ..utils.file_io import resolve_save_dir
from ..utils.paths import prompt_path, resource_path



class Model2DGenerator:
    """Generate 2.5D CST model VBA macros."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        save_dir: Optional[str] = None,
    ):
        self.vba_generator = VBAGenerator(default_model=model)
        self.prompt_files = [
            prompt_path("modeling_2d_prompt.md"),
            resource_path("modeling_2d.md"),
            resource_path("extrude_and_rotate.md"),
            resource_path("transform.md"),
        ]
        self.save_dir = resolve_save_dir(save_dir)

    def generate_model(
        self,
        description: Optional[str] = None,
        additional_prompt_files: Optional[List[str]] = None,
        save_as: str = "model_2d.bas",
    ) -> Optional[str]:
        """Generate a 2.5D CST model macro from a description."""
        prompt_files = self.prompt_files + (additional_prompt_files or [])
        return self.vba_generator.generate_vba(
            prompt_files=prompt_files,
            filename=os.path.join(self.save_dir, save_as),
            description=description,
            json_schema_hint=None,
            dimension_type="2.5D",
        )
