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
    Model2DGenerator,
    Model3DGenerator,
    ParameterGenerator,
    ParameterUpdater,
    StrongDescriptionToSolids,
)



def main() -> None:
    session_name = "vivaldi"
    output_dir = Path(__file__).resolve().parent / "output" / session_name
    output_dir.mkdir(parents=True, exist_ok=True)

    vivaldi_description = (
        "We are going to model a Vivaldi antenna. It should consist of a "
        "substrate, a tapered slot (on the front of the substrate), two "
        "rectangles and a circle for feeding (on the back of the substrate). "
        "The desired working frequency is from 3.0 - 13.5 GHz, so the "
        "substrate should be 30x20 mm (W x L). "
        "Consider the left bottom corner under the substrate as origin of "
        "axis (0,0,0). The substrate should be Rogers RO4003C of thickness ts "
        "(a fixed value 0.813), so the right top corner on the front is "
        "(30,20,ts). To model the tapered slot on the front, you need a full "
        "cover patch X-range [0,30], Y-range [0,20], "
        "Z-range [ts,ts+tp], tp should be a fixed value of 0.035. Then "
        "you need to use the patch to subtract a closed spline structure "
        "(extruded) and a circle. To form the slot, you need to model two "
        "symmetric splines and connect their top and bottom points to form a "
        "closed shape to extrude. The left spline is defined by 20 points, "
        "whose y are 20, 19, ... 1, and the X axis should be variables "
        "(20 variables). The point x values should be ascending within "
        "(0, 15), exclusive. Meanwhile, the right half X should be 30-X_i. "
        "Because the Vivaldi tapered slot is complex, add step-by-step "
        "instruction to the description. The circle's center is located at "
        "(15, gap+r1), and its radius should be r1 (2 variables). On the "
        "back, the first rectangle starts from the right, and should be X "
        "range [30-l1, 30], Y range [pf, pf+w1], Z range [-tp, 0], whose "
        "dimension is l1 x w1 x tp (2 parameters, tp is fixed). The second "
        "rectangle is X range [30-l1-l2, 30-l1], Y range [pf + 0.5 * "
        "(w1 - w2), pf + 0.5 * (w1 + w2)], Z range [-tp, 0], whose dimension "
        "is l2 x w2 x tp (2 parameters, tp is fixed). From a geometry view, "
        "the second rectangle is connected to the end of the first rectangle "
        "and aligned to the middle of it. Lastly, the circle on the back is a "
        "cylinder whose center is at (30-l1-l2, pf + 0.5 * w1) with radius r2 "
        "(1 variable) and Z range [-tp, 0]."
    )

    solids_generator = StrongDescriptionToSolids(save_dir=str(output_dir))
    solids = solids_generator.get_solids(
        description=vivaldi_description,
        save_as="vivaldi.json",
    )
    print(solids)

    parameter_generator = ParameterGenerator(save_dir=str(output_dir))
    parameters = parameter_generator.generate_parameters(
        description=vivaldi_description,
        output_file="vivaldi_parameters.bas",
        prompt_file=str(output_dir / "vivaldi.json"),
    )
    print(parameters)

    dimension_generator = DimensionGenerator(save_dir=str(output_dir))
    dimensions = dimension_generator.generate_dimensions(
        description=vivaldi_description,
        additional_prompt_files=[
            str(output_dir / "vivaldi.json"),
            str(output_dir / "vivaldi_parameters.bas"),
        ],
        save_as="vivaldi_dimensions.json",
    )
    print(dimensions)

    materials_processor = MaterialsProcessor(save_dir=str(output_dir))
    material_names = materials_processor.extract_materials(
        prompt_file=str(output_dir / "vivaldi_dimensions.json")
    )
    print("\nExtracted materials:", material_names)
    material_contents = materials_processor.process_material_files(
        material_names
    )
    vba_code = materials_processor.generate_vba_macro(
        material_contents,
        save_filename="vivaldi_materials.bas",
    )
    print(vba_code)

    model_3d_generator = Model3DGenerator(save_dir=str(output_dir))
    model_3d_code = model_3d_generator.generate_model(
        description=vivaldi_description,
        additional_prompt_files=[
            str(output_dir / "vivaldi_parameters.bas"),
            str(output_dir / "vivaldi_dimensions.json"),
            str(output_dir / "vivaldi_materials.bas"),
        ],
        save_as="vivaldi_model_3d.bas",
    )
    print(model_3d_code)

    model_2d_generator = Model2DGenerator(save_dir=str(output_dir))
    model_2d_code = model_2d_generator.generate_model(
        description=vivaldi_description,
        additional_prompt_files=[
            str(output_dir / "vivaldi_parameters.bas"),
            str(output_dir / "vivaldi_dimensions.json"),
            str(output_dir / "vivaldi_materials.bas"),
            str(output_dir / "vivaldi_model_3d.bas"),
        ],
        save_as="vivaldi_model_2d.bas",
    )
    print(model_2d_code)

    boolean_generator = BooleanOperationsGenerator(save_dir=str(output_dir))
    boolean_code = boolean_generator.generate_operations(
        description=vivaldi_description,
        additional_prompt_files=[
            str(output_dir / "vivaldi_parameters.bas"),
            str(output_dir / "vivaldi_dimensions.json"),
            str(output_dir / "vivaldi_model_2d.bas"),
            str(output_dir / "vivaldi_model_3d.bas"),
        ],
        save_as="vivaldi_boolean.bas",
    )
    print(boolean_code)

    update_prompt_files = [
        str(output_dir / "vivaldi_dimensions.json"),
        str(output_dir / "vivaldi_parameters.bas"),
    ]
    update_description = (
        "I want change spline definition's X_1 to X_20 values to form a "
        "Vivaldi shape and increase the rectangles length on the back and the "
        "radius of the circle on the back."
    )
    updater = ParameterUpdater(save_dir=str(output_dir))
    update_code = updater.generate_update(
        save_as="vivaldi_update_parameters.bas",
        description=update_description,
        additional_prompt_files=update_prompt_files,
    )
    print(update_code)

    vba_path = output_dir / "vivaldi_update_parameters.bas"
    project_path = output_dir / "vivaldi_antenna.cst"
    runner = CstRunner(
        create_new_if_none=False,
        project_path=str(project_path),
    )
    runner.set_parameter_tasks({"Update Parameters": str(vba_path)})
    runner.apply_parameter_updates(
        save_path=str(output_dir / "vivaldi_update_parameters.cst"),
        include_results=False,
        allow_overwrite=True,
        close_project_after_save=True,
    )



if __name__ == "__main__":
    main()
