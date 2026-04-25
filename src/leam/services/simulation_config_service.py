"""Natural-language to structured simulation config conversion."""

from typing import Any, Dict, Optional

from ..core import LLMCaller
from ..utils.json_utils import parse_json_maybe
from ..utils.paths import prompt_path


_SIM_CONFIG_SCHEMA_HINT = """
{
  "frequency": {
    "start": <number>,
    "stop": <number>,
    "unit": "GHz|MHz|kHz|Hz"
  },
  "boundary": {
    "xmin": "Open|PML|PEC|PMC|Symmetry|Open Add Space",
    "xmax": "Open|PML|PEC|PMC|Symmetry|Open Add Space",
    "ymin": "Open|PML|PEC|PMC|Symmetry|Open Add Space",
    "ymax": "Open|PML|PEC|PMC|Symmetry|Open Add Space",
    "zmin": "Open|PML|PEC|PMC|Symmetry|Open Add Space",
    "zmax": "Open|PML|PEC|PMC|Symmetry|Open Add Space"
  },
  "port": {
    "mode": "single",
    "reference_impedance": <number>
  },
  "solver": {
    "type": "auto|frequency_domain|time_domain"
  },
  "export": {
    "s11": {
      "format": "touchstone|csv"
    }
  }
}
""".strip()


class SimulationConfigService:
    """Parse natural language simulation intent into a JSON-like dict."""

    def __init__(self):
        self.llm = LLMCaller()

    def parse(self, natural_language: Optional[str]) -> Dict[str, Any]:
        text = (natural_language or "").strip()
        if not text:
            return {}

        result = self.llm.call_llm(
            prompt_files=[prompt_path("simulation_config_prompt.md")],
            description=text,
            json_schema_hint=_SIM_CONFIG_SCHEMA_HINT,
            reasoning_effort="low",
        )
        parsed = parse_json_maybe(result)
        if isinstance(parsed, dict):
            return parsed
        return {}
