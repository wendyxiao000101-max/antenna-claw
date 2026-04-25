# OpenClaw ↔ LEAM 接入手册

本文面向 OpenClaw 集成方，是 `leam` 包作为无交互后端服务的唯一权威接口文档。

LEAM 不再是带聊天循环的 CLI 应用，而是一组可以从 Python 或 RPC 直接调用的执行接口：

- `build_and_simulate` — 新建或复用一个输出目录，跑 template/new/rerun 流水线
- `get_project_context_snapshot` — 读取一个已有输出的上下文（参数列表、最近一次仿真摘要、白名单）
- `validate_optimization_request` — 优化请求的只读预检
- `optimize_parameters` — 在已存在的 `.cst` 工程上调用 CST Optimizer1D
- `list_templates` — 列出内置模板

所有调用都无副作用地返回结构化对象；所有失败都走**结构化错误**（不再抛 `ValueError` / `FileNotFoundError`），OpenClaw 可以根据 `code` 字段直接分发。

---

## 1. 职责边界

| 能力 | OpenClaw | LEAM |
| --- | --- | --- |
| 对话、记忆、多轮迭代 | ✔ | ✘ |
| 自然语言 → 结构化请求 | ✔ | ✘ |
| 意图分类（new / rerun / optimize） | ✔ | ✘ |
| Touchstone / CSV 的读图与 S11 总结 | ✔ | ✘ |
| 用户确认流程 | ✔ | ✘ |
| 模板匹配与结构化生成 | ✘ | ✔ |
| CST 建模、仿真、结果导出 | ✘ | ✔ |
| CST Optimizer1D 调用 | ✘ | ✔ |
| 优化请求的结构化校验 | ✘ | ✔ |
| 文件系统产物合同（`run.json` 等） | ✘ | ✔ |

LEAM 只向文件系统写产物。OpenClaw 负责把这些产物读回来做展示、总结、图形化。

---

## 2. 安装 / 使用

LEAM 是一个普通 Python 包：

```bash
pip install -e LEAM-main
```

运行时依赖：

- Python 3.9+
- `openai>=2.0.0`
- 执行 CST 阶段时：本机已安装 CST Studio Suite，并配置 `CST_PATH`（环境变量或 `config.json`）

环境自检：

```bash
leam doctor
```

从 OpenClaw 侧导入：

```python
from leam import (
    BuildAndSimulateRequest,
    OptimizationRequest,
    LeamService,
    # 或直接使用模块级函数
    build_and_simulate,
    get_project_context_snapshot,
    validate_optimization_request,
    optimize_parameters,
    list_templates,
)
```

`LeamService(project_root=...)` 与模块级函数两种形态等价；绝大多数场景下使用模块级函数即可，`LeamService` 只在需要复用实例时才显式构造。

### 2.1 部署到 OpenClaw 主机

LEAM 可以作为普通 Python 包随 OpenClaw 部署，但目标主机仍然需要单独准备运行环境：

| 项 | 要求 |
| --- | --- |
| Python | 3.9+ |
| Python 依赖 | `openai>=2.0.0` |
| CST | 需要执行 `run_cst=True` 或 `optimize_parameters` 时，必须安装 CST Studio Suite |
| CST Python 库 | `CST_PATH\AMD64\python_cst_libraries` 必须存在并可被加入 `PYTHONPATH` |
| OpenAI 凭据 | 设置 `OPENAI_API_KEY` 环境变量，或在目标主机本地创建 `config.json` |

推荐部署流程：

```powershell
# 在 LEAM-main 项目根目录生成交付包
.\package_release.ps1

# 将 dist\leam_openclaw_handoff.zip 拷贝到 OpenClaw 主机后解压
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install .\leam-0.3.0-py3-none-any.whl

# 目标主机配置。优先推荐环境变量，不要把真实 key 写进源码或交付包。
$env:OPENAI_API_KEY = "sk-..."
$env:CST_PATH = "C:\Program Files (x86)\CST Studio Suite 2025"

leam doctor
```

如果 OpenClaw 直接在同一进程内 `import leam`，LEAM 必须安装在 OpenClaw 使用的同一个 Python 环境里。如果 OpenClaw 通过子进程、HTTP 或其他 RPC 调用 LEAM，可以为 LEAM 单独创建虚拟环境，OpenClaw 只需要知道调用入口和输出目录。

交付包不要包含以下本机文件：

- `config.json`（可能包含真实 API key 和本机 CST 路径）
- `.venv/`、`.venv_broken/`
- `.pytest_cache/`、`__pycache__/`
- `examples/output/` 里的历史运行产物
- `dist/`、`build/` 之外的临时构建缓存

`config.example.json` 只作为模板；实际 `config.json` 应由 OpenClaw 主机本地创建，或完全改用 `OPENAI_API_KEY` / `CST_PATH` 环境变量。

---

## 3. 典型调用链

### 3.1 新建一个设计并仿真

```python
from leam import build_and_simulate, BuildAndSimulateRequest

result = build_and_simulate(
    BuildAndSimulateRequest(
        description="2.4 GHz 空气介质 PIFA，覆盖 2.4-2.5 GHz",
        output_name="pifa_24g",
        execution_mode="simulate_and_export",
        simulation_request="2.4-2.5GHz, Open Add Space, 50 Ohm",
        run_cst=True,
        prefer_template=True,
    )
)
```

`build_and_simulate` 内部自动：

1. 优先做模板匹配（`prefer_template=True`），命中则走 `TemplateWorkflow`
2. 未命中则走 `NewDesignWorkflow` 生成 6 件套，再接一段 `RerunWorkflow` 跑 CST
3. 所有产物落到 `examples/output/<output_name>/`
4. 最后写一份 `run.json` 作为 OpenClaw 的"单真相来源"

`BuildAndSimulateResult` 的关键字段：

| 字段 | 含义 |
| --- | --- |
| `workflow` | `"template"` / `"new"` / `"rerun"` |
| `output_name` | 本次会话名 |
| `output_dir` | 绝对路径，指向 `examples/output/<output_name>/` |
| `matched_template` | 模板是否命中 |
| `template_id` | 命中的模板 id（未命中为 None） |
| `paths` | 所有合同产物的绝对路径（见 §6） |
| `run_record_path` | `run.json` 的绝对路径 |
| `manifest_path` | `results/manifest.json`（存在时） |
| `simulation_audit_path` | `results/simulation_audit.json`（存在时） |
| `touchstone_path` | `results/sparams/s11.s1p`（存在时） |
| `s11_csv_path` | `results/sparams/s11.csv`（存在时） |

### 3.2 复用已有输出重新仿真

```python
result = build_and_simulate(
    BuildAndSimulateRequest(
        base_name="pifa_24g",
        execution_mode="simulate_only",
        simulation_request="1.8-2.8 GHz",
        run_cst=True,
    )
)
```

`base_name` 与 `description` **互斥**：rerun 路径只使用 `base_name`，不做模板匹配也不生成新 VBA。

### 3.3 用户对仿真结果不满意 → 调用优化器

```python
from leam import (
    get_project_context_snapshot,
    validate_optimization_request,
    optimize_parameters,
    OptimizationRequest,
)

# Step 1: 让 OpenClaw 的 LLM 看到"现在有哪些参数、最近一次仿真是什么"
snap = get_project_context_snapshot("pifa_24g")

# snap.parameters: [{"name": "Lp", "value": "30", "comment": "patch length"}, ...]
# snap.last_simulation: {"status": "success", "frequency": {...}, "s11_touchstone": "..."}
# snap.goal_templates / snap.algorithms / snap.schema_hint 全部注入 prompt

# Step 2: LLM 产出结构化 JSON，包装成 OptimizationRequest
req = OptimizationRequest(
    output_name="pifa_24g",
    variables=[
        {"name": "Lp", "min": 25.0, "max": 35.0},
        {"name": "Wp", "min": 15.0, "max": 25.0},
    ],
    goals=[
        {
            "template": "s11_min_at_frequency",
            "args": {"frequency_ghz": 2.45, "threshold_db": -15},
        }
    ],
    algorithm="Trust Region Framework",
    max_evaluations=40,
    natural_language="现在谐振频率太高了，在 25-35 mm 扫 Lp，把 2.45 GHz 压到 -15 dB",
)

# Step 3: 只读预检——不执行 CST，只返回错误/警告
check = validate_optimization_request(req)
if not check.is_valid:
    # 把 check.errors 翻译成中文问回用户，错误列表详见 §5
    return check.errors

# Step 4: 用户确认后再真正执行
result = optimize_parameters(req)

# result.best_parameters: {"Lp": "28.7", "Wp": "18.3"}
# result.status: "success" | "failed"
# result.optimization_manifest_path / best_parameters_path / history_path
```

---

## 4. API 参考

所有 dataclass 定义在 `leam.service_api`。

### 4.1 `build_and_simulate(request)`

请求：

```python
@dataclass
class BuildAndSimulateRequest:
    description: str = ""            # 新建/模板路径必填
    output_name: str = ""            # 新建/模板路径建议必填
    base_name: str = ""              # rerun 路径必填，与 description 互斥
    design_mode: str = "strong"      # "weak" | "strong"
    execution_mode: str = "simulate_and_export"
        # "build_only" | "simulate_only" | "simulate_and_export"
    simulation_request: str = ""     # 给 LLM 参考的频率/边界描述
    run_cst: bool = True
    prefer_template: bool = True
    enable_topology_check: bool = True
```

规则：

- `base_name` 与 `description` 必须二选一，不能同时给
- `execution_mode` 不在白名单会抛 `ValueError`（合法编程错误，建议 OpenClaw 在封装层先校验）
- `design_mode` 只影响 `new` 路径，`template` / `rerun` 忽略

### 4.2 `list_templates()`

返回所有内置模板的元数据列表：

```python
[
    {
        "template_id": "air_pifa",
        "name": "空气介质 PIFA",
        "version": "1.0",
        "antenna_type": "PIFA",
        "substrate": "air",
        "baseline_frequency_ghz": 2.4,
        "match_keywords": ["PIFA", "pifa", "平面倒F"],
        "match_substrate": ["air", "空气"],
        "editable_params": ["Lp", "Wp", "h", "sPins", "Lg", "Wg"],
        "locked_params": ["t_cu", "dPin", "gPort"],
    },
    ...
]
```

### 4.3 `get_project_context_snapshot(output_name)`

纯只读；绝不会 mkdir，也不会写任何文件。

返回 `ProjectContextSnapshot`：

```python
@dataclass
class ProjectContextSnapshot:
    output_name: str
    output_dir: str                     # 绝对路径，可能尚未存在
    exists: bool                        # output_dir 是否已落地
    has_cst_project: bool               # <name>.cst 是否存在
    has_parameters_bas: bool            # <name>_parameters.bas 是否存在
    parameters: List[Dict]              # [{name, value, comment}, ...]
    last_simulation: Dict               # 最近一次 run.json 的摘要
    goal_templates: List[Dict]          # 白名单 goal 模板 + 必填字段
    algorithms: List[str]               # 允许的 Optimizer1D 算法
    units: Dict[str, str]               # {"length": "mm", "frequency": "GHz"}
    schema_hint: Dict                   # OpenClaw 的 prompt schema 提示
```

`last_simulation` 的形状（字段在有数据时才出现）：

```python
{
    "status": "success" | "failed" | "running" | ...,
    "request": "原始 simulation_request",
    "frequency": {"start": 2.0, "stop": 3.0, "unit": "GHz"},
    "s11_touchstone": "examples/output/pifa_24g/results/sparams/s11.s1p",
    "run_record_schema_version": "1.0",
}
```

OpenClaw 典型用法：把 `parameters` / `goal_templates` / `algorithms` / `units` 作为系统消息注入 LLM，要求它仅输出满足 `schema_hint` 的 JSON。

### 4.4 `validate_optimization_request(request)`

只读；只访问 `<name>_parameters.bas`，不连 CST，不改任何文件。

返回 `OptimizationValidationResult`：

```python
@dataclass
class OptimizationValidationResult:
    is_valid: bool
    normalized: Optional[Dict]          # 合法时给出单位归一后的请求
    errors: List[Dict]                  # 每项都有 {code, field, message, suggestion}
    warnings: List[Dict]                # 同形状，仅提示
```

`normalized` 示例：

```python
{
    "output_name": "pifa_24g",
    "variables": [
        {"name": "Lp", "min": 25.0, "max": 35.0},
        {"name": "Wp", "min": 15.0, "max": 25.0, "init": 20.0},
    ],
    "goals": [
        {
            "template": "s11_min_at_frequency",
            "args": {"frequency_ghz": 2.45, "threshold_db": -15.0, "weight": 1.0},
        }
    ],
    "algorithm": "Trust Region Framework",
    "max_evaluations": 40,
    "use_current_as_init": True,
    "natural_language": "...",
    "notes": "",
    "known_parameters": ["Lg", "Lp", "Wg", "Wp", "dPin", "gPort", "h", "sPins", "t_cu"],
}
```

OpenClaw 应当优先使用 `normalized` 的值去渲染"本次优化将执行如下设置"确认界面。

### 4.5 `optimize_parameters(request)`

执行路径会先调用 `validate_optimization_request`，任何验证错误都会直接返回：

```python
OptimizationResult(
    output_name=request.output_name or "",
    status="failed",
    error="validation_failed",
    best_parameters={},
    optimization_manifest_path=None,
    optimization_audit_path=None,
    best_parameters_path=None,
    history_path=None,
)
```

OpenClaw 看到 `status="failed"` 且 `error="validation_failed"` 时，应当回到 `validate_optimization_request` 拿到具体错误列表。

成功返回：

```python
@dataclass
class OptimizationResult:
    output_name: str
    status: str                         # "success" | "failed"
    best_parameters: Dict[str, Any]     # {"Lp": "28.7", ...}
    optimization_manifest_path: Optional[str]
    optimization_audit_path: Optional[str]
    best_parameters_path: Optional[str]
    history_path: Optional[str]
    error: Optional[str]                # 非验证类错误的透传
```

CST 内部异常不会外抛，而是作为 `status="failed"` + `error=<message>` 透传。

### 4.6 `OptimizationRequest` 字段说明

```python
@dataclass
class OptimizationRequest:
    output_name: str
    variables: List[Dict]               # [{name, min, max, init?}]
    goals: List[Dict]                   # [{template, args}]
    algorithm: str = "Trust Region Framework"
    max_evaluations: int = 40
    use_current_as_init: bool = True
    natural_language: str = ""          # 原始用户表述，审计用
    notes: str = ""                     # OpenClaw 注释，审计用
```

- `variables[i].min` / `max` / `init` 可以是数字或 `"30mm"` / `"2.45 GHz"` 等字符串，LEAM 会自动提取数字部分
- `goals[i].template` 必须来自下面的白名单，`args` 以 GHz / dB 为默认单位，也可以写 `frequency_mhz` / `freq_start_hz` 等别名，验证器会换算
- `algorithm` 不在白名单时自动降级为 `"Trust Region Framework"` 并写一条 warning

---

## 5. Goal 模板白名单

所有 `goals[i].template` 只能来自下面三个值，其它全部拒绝。白名单源头在 `leam.services.GOAL_SCHEMA`。

### 5.1 `s11_min_at_frequency`

| 字段 | 必填 | 单位 | 默认 | 含义 |
| --- | --- | --- | --- | --- |
| `frequency_ghz` | ✔ | GHz | — | 目标谐振点 |
| `threshold_db` | ✘ | dB | `-10.0` | |S11| 要压到多少以下（负数） |
| `weight` | ✘ | — | `1.0` | goal 权重 |

别名：`frequency_mhz` / `frequency_hz` / `frequency_khz`（自动换算）。

示例：

```json
{"template": "s11_min_at_frequency", "args": {"frequency_ghz": 2.45, "threshold_db": -15}}
```

### 5.2 `bandwidth_max_in_band`

| 字段 | 必填 | 单位 | 默认 | 含义 |
| --- | --- | --- | --- | --- |
| `freq_start_ghz` | ✔ | GHz | — | 带宽起点 |
| `freq_stop_ghz` | ✔ | GHz | — | 带宽终点（必须 > 起点） |
| `threshold_db` | ✘ | dB | `-10.0` | 区间内 |S11| 低于阈值 |
| `weight` | ✘ | — | `1.0` | |

别名：`freq_start_mhz` / `freq_stop_mhz` 等。

示例：

```json
{
    "template": "bandwidth_max_in_band",
    "args": {"freq_start_ghz": 2.4, "freq_stop_ghz": 2.5, "threshold_db": -10}
}
```

### 5.3 `resonance_align_to_frequency`

| 字段 | 必填 | 单位 | 默认 | 含义 |
| --- | --- | --- | --- | --- |
| `frequency_ghz` | ✔ | GHz | — | 中心频点 |
| `tolerance_mhz` | ✘ | MHz | `50.0` | 搜索窗半宽，必须 > 0 |
| `weight` | ✘ | — | `1.0` | |

示例：

```json
{
    "template": "resonance_align_to_frequency",
    "args": {"frequency_ghz": 2.45, "tolerance_mhz": 50}
}
```

### 5.4 算法白名单

来自 `leam.services.ALLOWED_ALGORITHMS`：

- `Trust Region Framework`（默认）
- `Nelder Mead Simplex`
- `Interpolated Quasi Newton`
- `Classic Powell`
- `Genetic Algorithm`
- `Particle Swarm Optimization`

---

## 6. 错误与告警码表

所有 `errors[]` / `warnings[]` 元素形状统一：

```python
{"code": "STRING", "field": "variables[0].name", "message": "...", "suggestion": "..."}
```

### 6.1 请求级

| code | 含义 |
| --- | --- |
| `REQUEST_NOT_OBJECT` | 请求不是 JSON 对象 |
| `OUTPUT_NAME_REQUIRED` | `output_name` 为空或全空白 |
| `PROJECT_MISSING` | `examples/output/<name>/` 不存在 |
| `CST_PROJECT_MISSING` | 目录在，但 `<name>.cst` 不存在，优化无法执行 |
| `PARAMETERS_BAS_MISSING` | `<name>_parameters.bas` 不存在（warning，白名单将为空） |

### 6.2 变量级

| code | 级别 | 含义 |
| --- | --- | --- |
| `VARIABLES_REQUIRED` | error | `variables` 为空 |
| `VARIABLE_NOT_OBJECT` | error | 某个变量不是对象 |
| `VAR_NAME_REQUIRED` | error | 变量缺 `name` |
| `VAR_NAME_DUPLICATE` | error | `name` 在 variables 中重复 |
| `VAR_NAME_UNKNOWN` | error | `name` 不在项目的 ParameterList 中 |
| `VAR_MIN_INVALID` / `VAR_MAX_INVALID` / `VAR_INIT_INVALID` | error | 数值不能解析 |
| `VAR_RANGE_INVERTED` | error | `min >= max` |
| `VAR_INIT_OUT_OF_RANGE` | warning | `init` 不在 `[min, max]` 内，优化仍可执行但不推荐 |

### 6.3 Goal 级

| code | 级别 | 含义 |
| --- | --- | --- |
| `GOALS_REQUIRED` | error | `goals` 为空 |
| `GOAL_NOT_OBJECT` | error | goal 不是对象 |
| `GOAL_TEMPLATE_REQUIRED` | error | 缺 `template` |
| `GOAL_TEMPLATE_UNKNOWN` | error | 不在白名单 |
| `GOAL_ARGS_NOT_OBJECT` | error | `args` 不是对象 |
| `GOAL_ARG_REQUIRED` | error | 缺必填字段 |
| `GOAL_ARG_INVALID` | error | 字段不是数值 |
| `GOAL_ARG_UNKNOWN` | warning | 传了模板不认的字段，已忽略 |
| `GOAL_RANGE_INVERTED` | error | 带宽 goal 的起点 >= 终点 |
| `GOAL_TOLERANCE_INVALID` | error | `tolerance_mhz <= 0` |
| `GOAL_THRESHOLD_SIGN` | warning | `threshold_db > 0`，通常应为负数 |

### 6.4 算法与评估次数

| code | 级别 | 含义 |
| --- | --- | --- |
| `ALGORITHM_UNKNOWN` | warning | `algorithm` 不在白名单，已降级为默认值 |
| `MAX_EVAL_INVALID` | error | `max_evaluations` 不是整数 |
| `MAX_EVAL_TOO_LOW` | warning | `< 1`，已夹取到 `1` |
| `MAX_EVAL_TOO_HIGH` | warning | `> 500`，已夹取到 `500` |

---

## 7. 文件系统合同

每个 `output_name` 对应一个独立目录：

```text
examples/output/<output_name>/
├── run.json                        # 顶层单一来源（OpenClaw 只看这个就够）
├── <output_name>.json              # solids 定义
├── <output_name>_parameters.bas    # ParameterList 及 StoreParameters
├── <output_name>_dimensions.json   # 尺寸元数据
├── <output_name>_materials.bas
├── <output_name>_model.bas
├── <output_name>_boolean.bas
├── <output_name>.cst               # CST 工程（可选）
├── results/
│   ├── manifest.json               # 仿真状态 / 导出描述
│   ├── simulation_audit.json       # 仿真请求的 LLM 审计
│   └── sparams/
│       ├── s11.s1p                 # Touchstone
│       └── s11.csv                 # CSV 备份
└── results/optimization/
    ├── manifest.json               # 优化状态 / best parameters
    ├── audit.json                  # 优化请求的 LLM 审计
    ├── best_parameters.json        # 独立的最优参数快照
    ├── history.csv                 # 优化迭代历史（如启用）
    └── parameters_optimizer_safe.bas  # 去掉 StoreParameters 的副本
```

### 7.1 `run.json`

schema 版本：`"1.0"`；位置：`<output_dir>/run.json`；实现：[src/leam/infrastructure/run_record.py](../src/leam/infrastructure/run_record.py)。

```jsonc
{
    "schema_version": "1.0",
    "created_at_utc": "2026-04-23T06:00:00+00:00",
    "workflow": "template",                  // "template" | "new" | "rerun"
    "output_name": "pifa_24g",
    "execution_mode": "simulate_and_export",
    "run_cst": true,
    "description": "2.4 GHz 空气介质 PIFA ...",
    "simulation_request": "2.4-2.5GHz Open Add Space",
    "template": { "matched": true, "template_id": "air_pifa" },
    "artifacts": {
        "output_dir": "...",
        "solids_json":     {"path": "...", "exists": true, "size_bytes": 1234},
        "parameters_bas":  {...},
        "dimensions_json": {...},
        "materials_bas":   {...},
        "model_bas":       {...},
        "boolean_bas":     {...},
        "cst_project":     {...}
    },
    "results": {
        "manifest":         {"path": "...", "exists": true,  "size_bytes": 512},
        "simulation_audit": {"path": "...", "exists": true,  "size_bytes": 300},
        "s11_touchstone":   {"path": "...", "exists": true,  "size_bytes": 4321},
        "s11_csv":          {"path": "...", "exists": true,  "size_bytes": 2100}
    },
    "optimization": {
        "manifest":        {...},
        "audit":           {...},
        "best_parameters": {...},
        "history_csv":     {...}
    },
    "simulation_status": "success",
    "simulation_manifest_excerpt": { "status": "success", "frequency_ghz": {...}, ... },
    "simulation_audit_excerpt":    { "status": "success", ... },
    "optimization_status": "success"  // 或 null / "failed"
}
```

### 7.2 `results/manifest.json`

每次仿真成功后 LEAM 覆盖写入：

```jsonc
{
    "status": "success",
    "timestamp_utc": "...",
    "frequency_ghz": {"start": 2.0, "stop": 3.0, "unit": "GHz"},
    "solver": {"type": "frequency_domain", ...},
    "export": {"s11": {"format": "touchstone"}},
    "result_file": "examples/output/pifa_24g/results/sparams/s11.s1p",
    "result_format": "touchstone",
    "degraded_export": false,
    "source_project": "examples/output/pifa_24g/pifa_24g.cst"
}
```

失败时 `status: "failed"`，多一条 `error: "<message>"`。

### 7.3 `results/optimization/manifest.json`

```jsonc
{
    "status": "success",                    // 或 "failed" / "running"
    "timestamp_utc": "...",
    "mode": "optimizer",
    "algorithm": "Trust Region Framework",
    "max_evaluations": 40,
    "source_project": "...pifa_24g.cst",
    "variables": [{"name": "Lp", "min": 25.0, "max": 35.0}, ...],
    "goals": [
        {
            "template": "s11_min_at_frequency",
            "args": {"frequency_ghz": 2.45, "threshold_db": -15.0, "weight": 1.0},
            "description": "...",
            "vba_snippet": "With Optimizer1D\n .AddGoal\n ..."
        }
    ],
    "best_parameters": {"Lp": "28.7", "Wp": "18.3"}
}
```

失败时仍然写入，但 `status: "failed"` + `error: "..."`。

### 7.4 `results/optimization/best_parameters.json`

```jsonc
{
    "parameters": {"Lp": "28.7", "Wp": "18.3"},
    "seeds":      {"Lp": "30.0", "Wp": "20.0"},
    "variables":  [{"name": "Lp", "min": 25.0, "max": 35.0}, ...],
    "algorithm":  "Trust Region Framework"
}
```

OpenClaw 读这份文件即可得到"优化后的参数快照"，不需要解析 `manifest.json`。

### 7.5 `results/optimization/audit.json`

完整的优化审计：

```jsonc
{
    "natural_language": "现在谐振频率太高了...",
    "parsed_request": {
        "variables": [...],
        "goals": [...],
        "algorithm": "...",
        "max_evaluations": 40,
        "notes": ""
    },
    "variables": [...],
    "goals": [{...}],
    "algorithm": "...",
    "max_evaluations": 40,
    "use_current_as_init": true,
    "initial_parameters": {"Lp": "30.0", "Wp": "20.0", ...}
}
```

---

## 8. 模板约定

每个模板以一个目录存放在 `src/leam/templates/<template_id>/`，结构如下：

```text
<template_id>/
├── TEMPLATE.md              # YAML front-matter + 适用场景 / 参数说明
├── data/                    # baseline 参数 JSON
├── reference/               # 原始 CST VBA 参考
├── scripts/                 # 运行时代码（generator / validator / base）
│   └── __init__.py          # 暴露 <Name>Template 入口类
└── examples/                # 示例输入 + expected_output/
```

`TEMPLATE.md` 的 YAML front-matter 字段与 `list_templates()` 返回字段一一对应（`template_id` / `name` / `version` / `antenna_type` / `substrate` / `baseline_frequency_ghz` / `match_keywords` / `match_substrate` / `editable_params` / `locked_params`）。

命中规则（见 `template_runner.py`）：

1. 先用 `match_keywords` + `match_substrate` 做规则命中
2. 规则命中失败时才调 LLM top-1 建议
3. 两者都无命中则走 `new` 流水线

实际示例：`src/leam/templates/air_pifa/TEMPLATE.md`。

---

## 9. 设计决策 FAQ

**Q：为什么优化失败不抛异常？**
因为 OpenClaw 是对话式代理，抛异常会打断会话循环。所有失败都作为结构化结果返回，让 OpenClaw 决定怎么向用户复述。

**Q：为什么 `validate_optimization_request` 和 `get_project_context_snapshot` 绝不 mkdir？**
这两个接口会被 OpenClaw 在用户还没确认前反复调用；如果它们会副作用地创建目录，后续"项目不存在"的错误就永远不会再触发。内部用了一个显式 `_probe_output_dir` + `_resolve_paths_readonly` 的组合，绕开了 `OutputRepository.build_paths` 里的 `mkdir(exist_ok=True)`。

**Q：为什么 Python 直接写 `ParameterList`、VBA 历史只引用参数名？**
CST 在 Optimizer1D 运行期间会把 `ParameterList` 改为当前 trial value。如果 `<name>_parameters.bas` 里包含 `StoreParameters names, values`，CST 每次 history rebuild 都会覆盖掉 trial value，优化器就会"原地打转"。LEAM 在优化前会用 `strip_parameters_store_call` 拷一份去掉这行的副本（`parameters_optimizer_safe.bas`），同时用 Python API 一次性把初始值灌进 `ParameterList`。详见 [src/leam/tools/parameter_vba.py](../src/leam/tools/parameter_vba.py) 与 [src/leam/infrastructure/cst_gateway.py](../src/leam/infrastructure/cst_gateway.py) 的 `run_optimization`。

**Q：`execution_mode` 是什么？OpenClaw 需要理解吗？**
OpenClaw 只需要决定"要不要真的跑 CST"，其余用默认值即可：

- 新建 / 模板命中 + 想看 S11 → `"simulate_and_export"`
- 只生成几何 / 不连 CST → `"build_only"`
- 复用已有工程重跑 → `"simulate_only"`

LEAM 内部还会根据 workflow 做二次校验和回退，OpenClaw 不需要理解 build/simulate/export 之间的耦合规则。

**Q：模板没覆盖到的天线怎么办？**
`build_and_simulate` 在 `prefer_template=True` 时会优先走模板；模板无命中时自动退回到 `NewDesignWorkflow` + LLM 生成 + `RerunWorkflow` 连跑 CST。OpenClaw 不需要感知这个分支。

---

## 10. 变更影响速查

本次裁剪的破坏性变更（相对旧版 LEAM）：

- 删除：`leam.app` / `cli_leam.py` / `leam.agent.*` / 所有聊天 / 记忆 / session SQLite 存储
- 删除：`input()` 交互路径（参数审阅、拓扑修订等），全部改为确定性执行或 API 参数
- 新增：`service_api.py`（OpenClaw 入口）+ `run.json` 产物 + `optimization/` 产物
- 新增：`OptimizationValidationService` + goal 模板白名单 + `ProjectContextSnapshot`
- `OptimizationRequest` 验证失败不再抛异常，改为 `OptimizationResult(status="failed", error="validation_failed")`

如果 OpenClaw 之前曾经 import 过 `leam.app` / `leam.agent.*` / `leam.services.session_store` 等符号，需要全部迁移到 `leam.service_api` 的新接口。
