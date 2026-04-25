# Explicit Parameter Updates for OpenClaw

When a user has already seen simulation feedback, tried optimizer-driven
search, and then explicitly asks to change a known parameter for a known
purpose, OpenClaw can call LEAM without regenerating the design:

```python
from leam import apply_parameter_updates, ParameterUpdateRequest

result = apply_parameter_updates(
    ParameterUpdateRequest(
        output_name="pifa_24g",
        updates={"Lp": "28.5mm"},
        purpose="lower the resonant frequency",
        natural_language="把 Lp 改成 28.5mm，让谐振频率降低一点",
    )
)
```

This API is deterministic. OpenClaw is responsible for extracting the
structured `{parameter: value}` patch from the conversation. LEAM only
validates that the names exist in the generated ParameterList and then
patches the existing files.

Updated artifacts:

- `<output_name>_parameters.bas`
- `<output_name>.json`, when it contains a `parameters` object
- `<output_name>_dimensions.json`, when it contains a `parameters` object
- `run.json`, refreshed with `last_parameter_update`
- `results/parameter_updates/<timestamp>.json`, an audit record OpenClaw can
  use as memory/experience data

The other generated BAS files usually reference parameter names rather than
copying numeric values, so they remain valid without text replacement.

Result shape:

```python
@dataclass
class ParameterUpdateResult:
    output_name: str
    status: str
    changed_parameters: Dict[str, Dict[str, Any]]
    updated_files: Dict[str, str]
    audit_path: Optional[str]
    run_record_path: Optional[str]
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
```

Common errors:

- `OUTPUT_NAME_REQUIRED`
- `PROJECT_MISSING`
- `PARAMETERS_BAS_MISSING`
- `UPDATES_REQUIRED`
- `PARAMETER_UNKNOWN`
