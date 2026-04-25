"""Parameter BAS parsing and non-interactive editing service."""

import json
import re
from pathlib import Path
from typing import Dict, List

from ..utils.json_utils import parse_json_maybe
from .llm_assist import quick_llm


class ParameterService:
    NAME_RE = re.compile(
        r'names\s*\(\s*(\d+)\s*\)\s*=\s*"([^"]+)"\s*(?:\'(.*))?',
        re.IGNORECASE,
    )
    VALUE_RE = re.compile(
        r'values\s*\(\s*(\d+)\s*\)\s*=\s*"([^"]+)"',
        re.IGNORECASE,
    )

    @classmethod
    def parse_bas(cls, text: str) -> List[Dict]:
        names: Dict[int, str] = {}
        values: Dict[int, str] = {}
        comments: Dict[int, str] = {}
        for match in cls.NAME_RE.finditer(text):
            idx = int(match.group(1))
            names[idx] = match.group(2)
            comments[idx] = (match.group(3) or "").strip()
        for match in cls.VALUE_RE.finditer(text):
            idx = int(match.group(1))
            values[idx] = match.group(2)
        return [
            {
                "idx": idx,
                "name": names[idx],
                "value": values.get(idx, ""),
                "comment": comments.get(idx, ""),
            }
            for idx in sorted(names.keys())
            if idx in values
        ]

    @staticmethod
    def to_bas(params: List[Dict]) -> str:
        n = len(params)
        lines = [f"Dim names(1 To {n}) As String", f"Dim values(1 To {n}) As String", ""]
        for i, p in enumerate(params, 1):
            cmt = f"  ' {p['comment']}" if p.get("comment") else ""
            lines.append(f'names({i}) = "{p["name"]}"{cmt}')
            lines.append(f'values({i}) = "{p["value"]}"')
            lines.append("")
        lines.append("StoreParameters names, values")
        return "\n".join(lines)

    def load_params(self, bas_path: Path) -> List[Dict]:
        """Parse parameters from a .bas file without any interactive prompt."""
        return self.parse_bas(bas_path.read_text(encoding="utf-8"))

    def apply_instruction_file(self, bas_path: Path, request: str) -> bool:
        """Apply one-shot update request to a parameters BAS file."""
        params = self.parse_bas(bas_path.read_text(encoding="utf-8"))
        if not params:
            return False
        applied = self._apply_simple_edit(params, request) or self._apply_llm_edit(params, request)
        if not applied:
            return False
        bas_path.write_text(self.to_bas(params), encoding="utf-8")
        return True

    @staticmethod
    def _apply_simple_edit(params: List[Dict], line: str) -> bool:
        match = re.match(r"\s*(\w+)\s*[=:]\s*(.+)", line.strip())
        if not match:
            return False
        key, value = match.group(1).strip(), match.group(2).strip()
        value = re.sub(r"\s*(mm|GHz|MHz|Hz|mil)$", "", value, flags=re.IGNORECASE).strip()
        for param in params:
            if param["name"].lower() == key.lower():
                old = param["value"]
                param["value"] = value
                print(f"  ✓  {param['name']}: {old}  →  {value}")
                return True
        return False

    @staticmethod
    def _apply_llm_edit(params: List[Dict], request: str) -> bool:
        current = {p["name"]: p["value"] for p in params}
        system_prompt = (
            "You are helping edit CST antenna model parameters.\n"
            "Given current parameters and a user's modification request, "
            'return JSON: {"updates": {"param_name": "new_value", ...}, "note": "..."}\n'
            "Only include parameters that need to change. "
            "Values must be plain numbers or CST arithmetic expressions (no units).\n"
            f"Current parameters:\n{json.dumps(current, ensure_ascii=False)}"
        )
        raw = quick_llm(system_prompt, request)
        if not raw:
            return False
        parsed = parse_json_maybe(raw)
        if not isinstance(parsed, dict):
            return False
        updates = parsed.get("updates") or {}
        note = parsed.get("note") or ""
        if not updates:
            print(f"  [提示] {note or '未能识别修改指令，请尝试 参数名=新值 格式。'}")
            return False
        applied = False
        for key, val in updates.items():
            for param in params:
                if param["name"].lower() == key.lower():
                    old = param["value"]
                    param["value"] = str(val)
                    print(f"  ✓  {param['name']}: {old}  →  {val}")
                    applied = True
        if note:
            print(f"  [说明] {note}")
        return applied

