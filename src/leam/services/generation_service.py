"""Service that wraps tools/* generation calls stage by stage."""

from ..models import DesignSession
from ..tools import (
    BooleanOperationsGenerator,
    DimensionGenerator,
    MaterialsProcessor,
    Model3DGenerator,
    ParameterGenerator,
    StrongDescriptionToSolids,
    WeakDescriptionToSolids,
)


class GenerationService:
    def generate_solids(self, session: DesignSession) -> None:
        print("\n[生成 1/5] solids JSON…")
        cls = WeakDescriptionToSolids if session.mode == "weak" else StrongDescriptionToSolids
        cls(save_dir=str(session.paths.output_dir)).get_solids(
            description=session.description,
            save_as=session.paths.contract.json,
        )
        if not session.paths.json.exists():
            raise RuntimeError("solids JSON 生成失败。")

    def generate_parameters(self, session: DesignSession) -> None:
        print("[生成 2/5] 参数 VBA…")
        ParameterGenerator(save_dir=str(session.paths.output_dir)).generate_parameters(
            description=session.description,
            output_file=session.paths.contract.parameters,
            prompt_file=str(session.paths.json),
        )
        if not session.paths.parameters.exists():
            raise RuntimeError("参数 VBA 生成失败。")

    def generate_dimensions(self, session: DesignSession) -> None:
        print("\n[生成 3/5] 尺寸 JSON…")
        DimensionGenerator(save_dir=str(session.paths.output_dir)).generate_dimensions(
            description=session.description,
            additional_prompt_files=[
                str(session.paths.json),
                str(session.paths.parameters),
            ],
            save_as=session.paths.contract.dimensions,
        )
        if not session.paths.dimensions.exists():
            raise RuntimeError("尺寸 JSON 生成失败。")

    def generate_materials(self, session: DesignSession) -> None:
        print("[生成 4/5] 材料 VBA…")
        proc = MaterialsProcessor(save_dir=str(session.paths.output_dir))
        material_names = proc.extract_materials(prompt_file=str(session.paths.dimensions))
        material_contents = proc.process_material_files(material_names)
        proc.generate_vba_macro(material_contents, save_filename=session.paths.contract.materials)
        if not session.paths.materials.exists():
            raise RuntimeError("材料 VBA 生成失败。")

    def generate_model_and_boolean(self, session: DesignSession) -> None:
        print("[生成 5/5] 3D 模型 + 布尔操作 VBA…")
        Model3DGenerator(save_dir=str(session.paths.output_dir)).generate_model(
            description=session.description,
            additional_prompt_files=[
                str(session.paths.parameters),
                str(session.paths.dimensions),
                str(session.paths.materials),
            ],
            save_as=session.paths.contract.model,
        )
        BooleanOperationsGenerator(save_dir=str(session.paths.output_dir)).generate_operations(
            description=session.description,
            additional_prompt_files=[
                str(session.paths.parameters),
                str(session.paths.dimensions),
                str(session.paths.model),
            ],
            save_as=session.paths.contract.boolean,
        )
        if not session.paths.model.exists():
            raise RuntimeError("3D 模型 VBA 生成失败。")
        if not session.paths.boolean.exists():
            raise RuntimeError("布尔操作 VBA 生成失败。")

