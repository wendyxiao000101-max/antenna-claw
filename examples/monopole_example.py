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
    ParameterUpdater,
    StrongDescriptionToSolids,
)



def main() -> None:
    session_name = "monopole"
    output_dir = Path(__file__).resolve().parent / "output" / session_name
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = Path(__file__).resolve().parent / "assets"

    monopole_description = (
        "The layout of the slotted monopole antenna is shown in Fig. 4. "
        "The antenna is implemented on an FR-4 substrate with a thickness "
        "of 0.8 mm, a relative permittivity of 4.4, and a loss tangent of "
        "0.02. It consists of a driven circular patch radiator and two "
        "uniform rectangular metal planes separated by the microstrip line. "
        "Two slots are fused at the center of the driven circular patch "
        "radiator to form a quasi-cross slot, and the geometry of the slot "
        "helps control the surface current distribution. Meanwhile, the "
        "rectangular planes act as a coplanar partial ground."
    )

    solids_generator = StrongDescriptionToSolids(save_dir=str(output_dir))
    solids = solids_generator.get_solids(
        image_paths=[str(assets_dir / "Monopole.gif")],
        description=monopole_description,
        save_as="monopole.json",
    )
    print(solids)

    parameter_generator = ParameterGenerator(save_dir=str(output_dir))
    monopole_param_description = (
        "There are 12 variables. There is an error in the graph, SL should "
        "equal to ML + DPR + 0.2."
    )
    parameters = parameter_generator.generate_parameters(
        image_paths=[str(assets_dir / "Monopole_para.gif")],
        description=monopole_param_description,
        output_file="monopole_parameters.bas",
        prompt_file=str(output_dir / "monopole.json"),
    )
    print(parameters)

    dimension_generator = DimensionGenerator(save_dir=str(output_dir))
    monopole_dimension_description = (
        "SLH is the length of the horizontal slot on the x-axis. SLV is the "
        "length of the vertical slot on the y-axis. SLT is the width of both "
        "the rectangular slots. Two slots should be centered at the center "
        "of circle. IMPORTANT: RPL definition is not straightforward, the "
        "length of RP should be ML-RPL. The circle's center is at (SW/2, ML). "
        "The patch and the ground planes are all on the substrate."
    )
    dimensions = dimension_generator.generate_dimensions(
        description=monopole_dimension_description,
        image_paths=[str(assets_dir / "Monopole.gif")],
        additional_prompt_files=[
            str(output_dir / "monopole.json"),
            str(output_dir / "monopole_parameters.bas"),
        ],
        save_as="monopole_dimensions.json",
    )
    print(dimensions)

    materials_processor = MaterialsProcessor(save_dir=str(output_dir))
    material_names = materials_processor.extract_materials(
        prompt_file=str(output_dir / "monopole_dimensions.json")
    )
    print("\nExtracted materials:", material_names)
    material_contents = materials_processor.process_material_files(
        material_names
    )
    vba_code = materials_processor.generate_vba_macro(
        material_contents,
        save_filename="monopole_materials.bas",
    )
    print(vba_code)

    model_generator = Model3DGenerator(save_dir=str(output_dir))
    model_code = model_generator.generate_model(
        additional_prompt_files=[
            str(output_dir / "monopole_parameters.bas"),
            str(output_dir / "monopole_dimensions.json"),
            str(output_dir / "monopole_materials.bas"),
        ],
        save_as="monopole_model.bas",
    )
    print(model_code)

    boolean_generator = BooleanOperationsGenerator(save_dir=str(output_dir))
    monopole_boolean_description = (
        "We need add the feed to the patch then subtract slots from the patch."
    )
    boolean_code = boolean_generator.generate_operations(
        description=monopole_boolean_description,
        additional_prompt_files=[
            str(output_dir / "monopole_parameters.bas"),
            str(output_dir / "monopole_dimensions.json"),
            str(output_dir / "monopole_model.bas"),
        ],
        save_as="monopole_boolean.bas",
    )
    print(boolean_code)

    runner = CstRunner(create_new_if_none=False)
    vba_tasks = {
        "Parameters": str(output_dir / "monopole_parameters.bas"),
        "Materials": str(output_dir / "monopole_materials.bas"),
        "3D Model": str(output_dir / "monopole_model.bas"),
        "Boolean Operations": str(output_dir / "monopole_boolean.bas"),
    }
    runner.set_history_tasks(vba_tasks)
    project_path = output_dir / "monopole_antenna.cst"
    runner.create_project(str(project_path))

    update_prompt_files = [
        str(output_dir / "monopole_dimensions.json"),
        str(output_dir / "monopole_parameters.bas"),
    ]
    update_description = (
        "I want to demonstrate with the following parameters. "
        "$DP_{R}$ = 6.58, $S_{W}$ = 13.43, $SL_{T}$ = 1, $SL_{V}$ = 7.9, "
        "$SL_{H}$ = 7.9, $M_{L}$ = 25.08, $RP_{L}$ = 6.67, $M_{W}$ = 1.2, "
        "$M_{G}$ = 0.3, $S_{L}$ = 31.86, $RP_{W}$ = 5.815. (unit: mm.)}"
    )

    updater = ParameterUpdater(save_dir=str(output_dir))
    update_code = updater.generate_update(
        save_as="monopole_update_parameters.bas",
        description=update_description,
        additional_prompt_files=update_prompt_files,
    )
    print(update_code)

    vba_path = output_dir / "monopole_update_parameters.bas"
    runner = CstRunner(
        create_new_if_none=False,
        project_path=str(project_path),
    )
    runner.set_parameter_tasks({"Update Parameters": str(vba_path)})
    runner.apply_parameter_updates(
        save_path=None,
        close_project_after_save=False,
    )



if __name__ == "__main__":
    main()
