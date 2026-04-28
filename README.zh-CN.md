# LEAM

![LEAM Logo](assets/brand/leam-logo.png)

[English README](README.md)

LEAM (LLM-Enabled Antenna Modeling) 是面向 OpenClaw 的无交互 Python 后端。它把结构化的天线设计请求转换成可复现的 CST Studio Suite 产物：模型文件、仿真导出、优化器运行结果和参数更新记录。

OpenClaw 负责对话、意图路由、用户确认、S 参数分析、绘图和设计判断。LEAM 负责稳定执行。

## LEAM 提供什么

稳定入口都可以从 `leam` 顶层导入：

```python
from pathlib import Path

from leam import (
    BuildAndSimulateRequest,
    OptimizationRequest,
    ParameterUpdateRequest,
    build_and_simulate,
    get_project_context_snapshot,
    list_templates,
    optimize_parameters,
    validate_optimization_request,
    apply_parameter_updates,
)
```

主要能力：

- 基于模板、新建或复用目录生成天线模型。
- 创建 CST 工程、运行仿真、导出 S11 CSV。
- 调用 CST Optimizer，并提供预检、预算控制和结果诊断。
- 对已生成参数做确定性的后处理修改。
- 为 OpenClaw 提供 `examples/output/<output_name>/` 文件系统合同。

当前内置模板包括空气介质 PIFA，位于 `src/leam/templates/air_pifa`。

## 安装

```powershell
cd antenna-claw
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

如果要调用 CST Studio Suite 2023，请使用 CST Python 库支持的 Python 版本。实践中，Python 3.9 是 CST 后端运行的安全选择。

打包数据包括：

- `prompts/*.md`
- `resources/*.md`
- `templates/*/TEMPLATE.md`
- `templates/*/data/*.json`

## 配置

可以创建本地 `config.json`，也可以设置 LEAM 专用环境变量。

`config.json` 示例：

```json
{
  "cst_path": "C:\\Program Files\\CST Studio Suite 2023",
  "openai_api_key": "YOUR_API_KEY"
}
```

环境变量：

- `CST_PATH`: CST Studio Suite 安装根目录。
- `LEAM_OPENAI_API_KEY`: 只供 LEAM 使用的 OpenAI API key。
- `LEAM_ALLOW_GLOBAL_OPENAI_API_KEY=1`: 显式允许 LEAM 读取通用 `OPENAI_API_KEY`。

默认情况下，LEAM 不读取通用 `OPENAI_API_KEY`。这样可以避免 OpenClaw 或 Codex 这样的宿主进程把其他 OpenAI SDK 调用误导到用户为 LEAM 准备的付费 key 上。

环境自检：

```powershell
leam doctor
```

`doctor` 会检查：

- LEAM 是否能拿到 OpenAI key。
- CST 安装路径。
- CST materials 路径。
- CST Python libraries 路径。

## 核心流程

### 建模与仿真

```python
result = build_and_simulate(
    BuildAndSimulateRequest(
        description="2.45 GHz air substrate PIFA antenna",
        output_name="pifa_demo",
        execution_mode="simulate_and_export",
        simulation_request="2.0-3.0GHz Open Add Space 50 Ohm",
        run_cst=True,
        prefer_template=True,
    ),
    project_root=Path.cwd(),
)
```

执行模式：

- `build_only`: 只生成 JSON/BAS 产物。
- `simulate_and_export`: 创建 CST 工程、运行 solver、导出 S11。
- `simulate_only`: 对已有 output 目录重新仿真。

### 优化

优化被设计成两步：

1. 调用 `validate_optimization_request`。
2. 把归一化后的变量、目标和预算展示给用户并获得确认。
3. 调用 `optimize_parameters`。

```python
req = OptimizationRequest(
    output_name="pifa_demo",
    variables=[
        {"name": "Lp", "min": 17.2, "max": 18.4},
        {"name": "sPins", "min": 0.8, "max": 1.8},
    ],
    goals=[
        {
            "template": "resonance_align_to_frequency",
            "args": {
                "frequency_ghz": 2.45,
                "target_db": -30,
                "tolerance_mhz": 50,
            },
        }
    ],
    algorithm="Nelder Mead Simplex",
    max_evaluations=20,
)

validation = validate_optimization_request(
    req,
    project_root=Path.cwd(),
)

if validation.is_valid:
    # OpenClaw 必须把 validation.normalized["optimizer_budget"] 展示给用户，
    # 并在获得确认后再运行 CST。
    result = optimize_parameters(
        req,
        project_root=Path.cwd(),
    )
```

支持的算法：

- `Trust Region Framework`
- `Nelder Mead Simplex`
- `Interpolated Quasi Newton`
- `Classic Powell`
- `Genetic Algorithm`
- `Particle Swarm Optimization`

支持的目标模板：

- `s11_min_at_frequency`
- `bandwidth_max_in_band`
- `resonance_align_to_frequency`

### 优化预算语义

`max_evaluations` 永远表示用户允许的总 solver-run 预算。

对 Nelder Mead、Trust Region 等局部优化器，LEAM 会直接映射到 CST `SetMaxEval`。

对 `Particle Swarm Optimization` 和 `Genetic Algorithm` 这类群体算法，CST 使用的是迭代次数和种群大小。LEAM 会在 validation 阶段计算 `optimizer_budget`：

```json
{
  "requested_max_evaluations": 36,
  "algorithm_family": "population",
  "cst_limit_type": "iterations",
  "max_iterations": 4,
  "population_size": 8,
  "estimated_solver_runs": 32,
  "budget_policy": "strict_total_solver_runs",
  "requires_user_confirmation": true,
  "population_size_control": "SetGenerationSize"
}
```

默认种群大小：

```text
min(12, max(4, 2 * variable_count + 2))
```

如果显式传入的 `max_iterations * population_size` 超过 `max_evaluations`，validation 会失败。这样可以避免用户说“36 次评估”，但 CST 实际跑成几百甚至上千次 solver。

### 显式参数更新

当 OpenClaw 想直接修改已知生成参数、而不是重新生成设计时，使用这个接口：

```python
apply_parameter_updates(
    ParameterUpdateRequest(
        output_name="pifa_demo",
        updates={"Lp": 17.6, "sPins": 1.3},
        purpose="Retune resonance after S11 review",
    ),
    project_root=Path.cwd(),
)
```

LEAM 只接受当前 ParameterList 中已经存在的参数名。

## 输出目录合同

每个 `output_name` 对应一个目录：

```text
examples/output/<output_name>/
|-- run.json
|-- <output_name>.json
|-- <output_name>_parameters.bas
|-- <output_name>_dimensions.json
|-- <output_name>_materials.bas
|-- <output_name>_model.bas
|-- <output_name>_boolean.bas
|-- <output_name>.cst
`-- results/
    |-- manifest.json
    |-- simulation_audit.json
    |-- sparams/
    |   |-- s11.csv
    |   `-- s11.s1p
    `-- optimization/
        |-- manifest.json
        |-- audit.json
        |-- best_parameters.json
        `-- history.csv
```

说明：

- `run.json` 是 output 目录的根记录。
- 对 CST 2023，S11 导出优先使用 CSV。
- 如果 CST 的 `TOUCHSTONE.Write` 失败，Touchstone 导出会降级为 CSV。
- 优化状态和 solver 诊断写在 `results/optimization/manifest.json`。

## CST 集成说明

LEAM 使用 CST 的 `Optimizer` 对象，而不是旧的 `Optimizer1D` API。

重要行为：

- 优化器配置和启动通过 inline VBA 执行，不作为可见 History 步骤加入工程。
- S11 CSV 直接从 CST `ResultTree` 读取，不依赖当前选中的图表视图，也不依赖 `ASCIIExport`。
- LEAM 会解析 CST 优化器结果文件，例如 `Result/Model.opt` 和 `Result/Model_ui.opt`。
- solver error、没有新 solver evaluation、best parameters 回读失败都会被报告为优化失败，而不是静默当作成功。

## 开发

```powershell
cd antenna-claw
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
pytest tests -q
```

构建 wheel：

```powershell
python -m pip wheel . -w dist
```

本地运行产物会被 git 忽略：

- `config.json`
- `.env`
- 虚拟环境
- `dist/`, `build/`
- `examples/output/**`

## 已移除的旧接口

当前包是无交互后端。不要再使用以下旧路径：

- `leam.app`
- `leam.agent.*`
- 旧 SQLite session-store 模块
- 交互式 CLI/chat loop
- 基于 `input()` 的确认流程

OpenClaw 负责对话和确认。LEAM 负责确定性执行。

## License

MIT. See [LICENSE](LICENSE).
