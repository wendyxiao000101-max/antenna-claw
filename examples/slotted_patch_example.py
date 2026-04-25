import sys
from pathlib import Path

# Add the project root directory to the Python path for imports.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from leam.tools import (
    BooleanOperationsGenerator,
    CstRunner,
    DimensionGenerator,
    MaterialsProcessor,
    Model3DGenerator,
    ParameterGenerator,
    WeakDescriptionToSolids,
)



def main() -> None:
    session_name = "slotted_patch"
    output_dir = Path(__file__).resolve().parent / "output" / session_name
    output_dir.mkdir(parents=True, exist_ok=True)

    slotted_patch_description = (
        "I want to design a rectangular-slotted rectangular-patch antenna "
        "working at 2.45GHz."
    )

    solids_generator = WeakDescriptionToSolids(save_dir=str(output_dir))
    solids = solids_generator.get_solids(
        description=slotted_patch_description,
        save_as="slotted_patch_antenna.json",
    )
    print(solids)

    parameter_generator = ParameterGenerator(save_dir=str(output_dir))
    parameters = parameter_generator.generate_parameters(
        description=slotted_patch_description,
        output_file="slotted_patch_parameters.bas",
        prompt_file=str(output_dir / "slotted_patch_antenna.json"),
    )
    print(parameters)

    dimension_generator = DimensionGenerator(save_dir=str(output_dir))
    dimensions = dimension_generator.generate_dimensions(
        description=slotted_patch_description,
        additional_prompt_files=[
            str(output_dir / "slotted_patch_antenna.json"),
            str(output_dir / "slotted_patch_parameters.bas"),
        ],
        save_as="slotted_patch_dimensions.json",
    )
    print(dimensions)

    materials_processor = MaterialsProcessor(save_dir=str(output_dir))
    material_names = materials_processor.extract_materials(
        prompt_file=str(output_dir / "slotted_patch_dimensions.json")
    )
    print("\nExtracted materials:", material_names)
    material_contents = materials_processor.process_material_files(
        material_names
    )
    vba_code = materials_processor.generate_vba_macro(
        material_contents,
        save_filename="slotted_patch_materials.bas",
    )
    print(vba_code)

    model_generator = Model3DGenerator(save_dir=str(output_dir))
    model_code = model_generator.generate_model(
        description=slotted_patch_description,
        additional_prompt_files=[
            str(output_dir / "slotted_patch_parameters.bas"),
            str(output_dir / "slotted_patch_dimensions.json"),
            str(output_dir / "slotted_patch_materials.bas"),
        ],
        save_as="slotted_patch_model.bas",
    )
    print(model_code)

    boolean_generator = BooleanOperationsGenerator(save_dir=str(output_dir))
    boolean_code = boolean_generator.generate_operations(
        description=slotted_patch_description,
        additional_prompt_files=[
            str(output_dir / "slotted_patch_parameters.bas"),
            str(output_dir / "slotted_patch_dimensions.json"),
            str(output_dir / "slotted_patch_model.bas"),
        ],
        save_as="slotted_patch_boolean.bas",
    )
    print(boolean_code)

    runner = CstRunner(create_new_if_none=False)
    vba_tasks = {
        "Parameters": str(output_dir / "slotted_patch_parameters.bas"),
        "Materials": str(output_dir / "slotted_patch_materials.bas"),
        "3D Model": str(output_dir / "slotted_patch_model.bas"),
        "Boolean Operations": str(output_dir / "slotted_patch_boolean.bas"),
    }
    runner.set_history_tasks(vba_tasks)
    project_path = output_dir / "slotted_patch_antenna.cst"
    runner.create_project(str(project_path))



if __name__ == "__main__":
    main()
