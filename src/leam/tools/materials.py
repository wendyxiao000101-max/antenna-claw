import json
import os
from typing import List, Optional

from ..core.llm_caller import LLMCaller
from ..core.vba_generator import VBAGenerator
from ..utils.constants import DEFAULT_MODEL
from ..utils.file_io import process_text_files, resolve_save_dir
from ..utils.json_utils import ensure_json_filename, parse_json_maybe
from ..utils.paths import prompt_path



class MaterialsProcessor:
    """Extract materials and generate CST import macros."""

    EXTRACT_PROMPT_PATH = prompt_path("materials_extract_prompt.md")
    GENERATE_PROMPT_PATH = prompt_path("materials_vba_prompt.md")

    def __init__(
        self,
        save_dir: Optional[str] = None,
        cst_path: Optional[str] = None,
    ):
        self.config = self._load_config()
        self.cst_base_path = (
            cst_path
            or self.config.get("cst_path")
            or os.environ.get("CST_PATH")
        )

        self.cst_material_path = None
        if self.cst_base_path:
            self.cst_material_path = os.path.join(
                self.cst_base_path, "Library", "Materials"
            )
            if not os.path.exists(self.cst_material_path):
                raise ValueError(
                    "Material library path not found: "
                    f"{self.cst_material_path}"
                )

        self.llm_caller = LLMCaller(default_model=DEFAULT_MODEL)
        self.vba_generator = VBAGenerator(default_model=DEFAULT_MODEL)
        self.save_dir = resolve_save_dir(save_dir)

    def _load_config(self) -> dict:
        """Load configuration from config.json, if present."""
        current = os.path.abspath(os.path.dirname(__file__))
        config_path = None
        for _ in range(6):
            candidate = os.path.join(current, "config.json")
            if os.path.exists(candidate):
                config_path = candidate
                break
            current = os.path.dirname(current)
        if not config_path:
            return {}
        with open(config_path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)

    def _list_available_materials(self) -> List[str]:
        """List .mtd material filenames from the CST material library."""
        if not self.cst_material_path:
            print(
                "Warning: cst_path not configured. Configure config.json or "
                "CST_PATH to list materials."
            )
            return []

        if not os.path.isdir(self.cst_material_path):
            raise ValueError(
                f"Material library path not found: {self.cst_material_path}"
            )

        materials = []
        for entry in os.listdir(self.cst_material_path):
            full_path = os.path.join(self.cst_material_path, entry)
            if os.path.isfile(full_path) and entry.lower().endswith(".mtd"):
                materials.append(entry)

        materials.sort(key=str.casefold)
        return materials

    def extract_materials(
        self, prompt_file: str, save_as: Optional[str] = None
    ) -> List[str]:
        """
        Extract material names from an antenna description file.
        """
        material_names = self._list_available_materials()
        if not material_names:
            if save_as:
                self._save_materials_json([], save_as)
            return []

        available_materials = "\n".join(material_names)
        description = process_text_files([prompt_file])

        schema_hint = (
            "Return JSON with shape: "
            '{ "representation": "materials", '
            '"items": [ { "name": string, "path": string|null, '
            '"notes": string } ] }'
        )
        response = self.llm_caller.call_llm(
            prompt_files=[self.EXTRACT_PROMPT_PATH],
            description=(
                f"{description}\n\nAvailable materials:\n{available_materials}"
            ),
            json_schema_hint=schema_hint,
        )

        materials: List[str] = []
        parsed = parse_json_maybe(response)
        if isinstance(parsed, dict):
            for item in parsed.get("items", []) or []:
                name = str(item.get("name", "")).strip()
                if name:
                    if name.endswith(".mtd"):
                        materials.append(name)
                    else:
                        materials.append(f"{name}.mtd")
        elif isinstance(response, str):
            for name in response.splitlines():
                name = name.strip()
                if not name or not name.endswith(".mtd"):
                    continue
                materials.append(name)

        if save_as:
            self._save_materials_json(materials, save_as)

        return materials

    def _save_materials_json(
        self, materials: List[str], save_as: str
    ) -> None:
        save_path = os.path.join(self.save_dir, ensure_json_filename(save_as))
        payload = {
            "representation": "materials",
            "items": [{"name": name} for name in materials],
        }
        try:
            with open(save_path, "w", encoding="utf-8") as output_file:
                json.dump(payload, output_file, indent=2)
        except Exception as exc:
            print(f"Error saving materials JSON: {exc}")

    def process_material_files(self, material_names: List[str]) -> str:
        """Load material file contents for LLM input."""
        if not self.cst_material_path:
            print(
                "Warning: cst_path not configured. Provide it via "
                "config.json, env CST_PATH, or "
                "MaterialsProcessor(cst_path=...). "
                "Returning empty material contents."
            )
            return ""
        if not os.path.exists(self.cst_material_path):
            raise ValueError(
                f"Material library path not found: {self.cst_material_path}"
            )

        material_files = []
        for name in material_names:
            name = name.strip()
            if not name:
                continue

            material_path = os.path.normpath(
                os.path.join(self.cst_material_path, name)
            )
            if os.path.exists(material_path):
                material_files.append(material_path)
            else:
                print(f"Material file not found: {material_path}")

        return process_text_files(material_files) if material_files else ""

    def generate_vba_macro(
        self, material_contents: str, save_filename: Optional[str] = None
    ) -> str:
        """Generate a VBA macro for importing materials."""
        if not material_contents:
            return ""

        save_filename = save_filename or "materials.bas"
        save_path = os.path.join(self.save_dir, save_filename)

        code = self.vba_generator.generate_vba(
            prompt_files=[self.GENERATE_PROMPT_PATH],
            filename=save_path,
            description=material_contents,
            json_schema_hint=None,
            dimension_type="3d",
        )

        # Defensive: strip a stray leading language tag, if present.
        if isinstance(code, str):
            stripped = code.lstrip("\ufeff").lstrip()
            lines = stripped.splitlines()
            first = lines[0].strip().lower() if lines else ""
            if first in {"vb", "vba", "visualbasic"}:
                code = "\n".join(lines[1:]).lstrip()
                try:
                    with open(save_path, "w", encoding="utf-8") as output_file:
                        output_file.write(code)
                except Exception:
                    pass

        return code
