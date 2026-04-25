# Debugging Summary: Tool Debug Workflow

## Core Logic
When debugging any tool, go to the tool implementation and locate the
corresponding markdown files that define its prompts/resources. Update
those markdowns (and any schema hints in the tool) to align the output
structure with what downstream steps need.

## Steps
1) Identify the tool entry point in `src/leam/tools` (for example,
   `dimension_generator.py`, `model_3d_generator.py`, `materials.py`,
   `boolean_ops.py`, `strong_description_to_solids.py`,
   `weak_description_to_solids.py`, `parameter_generator.py`,
   `parameter_update.py`).
2) Inspect the tool for the prompt/resource paths (all `.md` files).
   - Prompts live in `src/leam/prompts`.
   - Resources live in `src/leam/resources`.
3) Adjust the relevant prompt/resource markdown to enforce the desired
   output format and constraints.
4) If the tool uses a JSON schema hint, keep it consistent with the
   updated prompt output shape.
5) Re-run the tool on a known example to verify the output structure
   and content.

## Mapping Reference (Examples)
- Dimension: `src/leam/tools/dimension_generator.py` ->
  `src/leam/prompts/dimension_prompt.md`
- Model3D: `src/leam/tools/model_3d_generator.py` ->
  `src/leam/prompts/modeling_3d_prompt.md`,
  `src/leam/resources/modeling_3d.md`
- Model2D: `src/leam/tools/model_2d_generator.py` ->
  `src/leam/prompts/modeling_2d_prompt.md`,
  `src/leam/resources/modeling_2d.md`,
  `src/leam/resources/extrude_and_rotate.md`,
  `src/leam/resources/transform.md`
- Materials: `src/leam/tools/materials.py` ->
  `src/leam/prompts/materials_extract_prompt.md`,
  `src/leam/prompts/materials_vba_prompt.md`
- Boolean: `src/leam/tools/boolean_ops.py` ->
  `src/leam/prompts/boolean_prompt.md`,
  `src/leam/resources/boolean_operations.md`
- D2S (Strong/Weak): `src/leam/tools/strong_description_to_solids.py` /
  `src/leam/tools/weak_description_to_solids.py` ->
  `src/leam/prompts/strong_description_to_solids.md` /
  `src/leam/prompts/weak_description_to_solids.md`
- Parameterize: `src/leam/tools/parameter_generator.py` ->
  `src/leam/prompts/parameter_prompt.md`
- UpdateParameter: `src/leam/tools/parameter_update.py` ->
  `src/leam/prompts/parameter_update_prompt.md`

## Verification Step
Re-run the target tool with a representative input and confirm the
output structure matches the updated markdown requirements.
