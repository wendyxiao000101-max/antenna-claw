from typing import List, Optional

from .llm_caller import LLMCaller
from ..utils.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from ..utils.json_utils import parse_json_maybe



class VBAGenerator:
    def __init__(self, default_model: str = DEFAULT_MODEL):
        """Initialize the VBA generator."""
        self.llm_caller = LLMCaller(default_model=default_model)

    def _extract_vba_code(self, result: str) -> str:
        """Extract VBA code from the LLM response."""

        def _sanitize_vba_text(text: str) -> str:
            # Drop a leading language tag like "vb" or "vba".
            candidate = (text or "").lstrip("\ufeff").lstrip()
            lines = candidate.splitlines()
            first_line = lines[0].strip().lower() if lines else ""
            if first_line in {"vb", "vba", "visualbasic"}:
                return "\n".join(lines[1:]).lstrip()
            return candidate

        result = _sanitize_vba_text(result or "")

        parsed = parse_json_maybe(result)
        if isinstance(parsed, dict):
            macro = (
                parsed.get("vba_macro")
                or parsed.get("content")
                or parsed.get("macro")
            )
            if isinstance(macro, str) and macro.strip():
                return macro.strip()

        if "```vba" in result:
            try:
                return result.split("```vba")[1].split("```")[0].strip()
            except IndexError:
                return result
        if result.startswith("```") and result.endswith("```"):
            return result.strip("```").strip()
        return _sanitize_vba_text(result)

    def _save_to_file(self, code: str, filename: str) -> None:
        """Save VBA code to a .bas file."""
        if not filename.lower().endswith(".bas"):
            filename += ".bas"

        # Ensure we never write a stray language tag line.
        code = code.lstrip("\ufeff")
        if code.lstrip().lower().startswith(("vb\n", "vba\n")):
            code = "\n".join(code.lstrip().splitlines()[1:]).lstrip()

        with open(filename, "w", encoding="utf-8") as output_file:
            output_file.write(code)

    def generate_vba(
        self,
        prompt_files: List[str],
        filename: str,
        model: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        description: Optional[str] = None,
        reasoning_effort: Optional[str] = DEFAULT_REASONING_EFFORT,
        json_schema_hint: Optional[str] = None,
        dimension_type: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate and save VBA code based on the prompts and inputs.
        """
        try:
            result = self.llm_caller.call_llm(
                prompt_files=prompt_files,
                model=model,
                image_paths=image_paths,
                description=description,
                reasoning_effort=reasoning_effort,
                json_schema_hint=json_schema_hint,
            )

            if not result:
                return None

            vba_code = self._extract_vba_code(result)

            # Final guard: strip any accidental leading language tags.
            vba_stripped = vba_code.lstrip("\ufeff").lstrip()
            lines = vba_stripped.splitlines()
            first_line = lines[0].strip().lower() if lines else ""
            if first_line in {"vb", "vba", "visualbasic"}:
                vba_code = "\n".join(lines[1:]).lstrip()

            try:
                self._save_to_file(vba_code, filename)
            except Exception as exc:
                print(f"Error saving VBA file: {exc}")

            return vba_code

        except Exception as exc:
            print(f"Error generating VBA code: {exc}")
            return None
