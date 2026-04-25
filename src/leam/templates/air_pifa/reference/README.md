# Air-PIFA 参考建模脚本

本目录存放空气介质 PIFA 模板的**参考建模脚本**，不参与运行时自动生成流程，仅作为：

- 模板拓扑的权威来源（Single Source of Truth）
- 核对 `scripts/pifa_generator.py` 产出结果的对照样例
- 手动在 CST 中导入以验证模型合理性的一体化宏

## 文件说明

| 文件 | 用途 |
|------|------|
| `PIFA建模.bas` | 完整 CST VBA 宏，包含 Units / Parameters / Materials / Geometry / Boolean 五个子过程，可在 CST 中直接 Run Macro。 |

## 与 `scripts/` 的关系

`scripts/pifa_generator.py` 会将同样的拓扑拆分输出为 6 个产物文件（`*_parameters.bas`、`*_materials.bas`、`*_model.bas`、`*_boolean.bas`、`*.json`、`*_dimensions.json`），便于按需分段导入和自动化流水线。

若需验证拆分版本与参考版本一致，可对比：

- `PIFA建模.bas` 的 `DefineParameters` ↔ 生成的 `*_parameters.bas`
- `PIFA建模.bas` 的 `BuildGeometry` ↔ 生成的 `*_model.bas`
- `PIFA建模.bas` 的 `BooleanConnect` ↔ 生成的 `*_boolean.bas` 的 Solid.Add 部分

## 注意

- 参考宏未包含 DiscretePort 创建（仅几何 + 布尔），端口由 `scripts/pifa_generator.py` 在 `*_boolean.bas` 末尾追加。
- 参考宏中的参数数值为最新的人工校准版本；`data/optimized_pifa_params.json` 仍是自动流程使用的 baseline，二者略有差异属正常现象（后者未来可同步更新）。
