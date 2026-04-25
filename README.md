# LEAM

![LEAM Logo](assets/brand/leam-logo.png)

> **LEAM 是为 [OpenClaw](https://github.com/openclaw) 提供天线建模、仿真与 CST Optimizer 调用的无交互后端服务。**
> 所有聊天、意图识别、S 参数分析、多轮迭代都由 OpenClaw 承担；LEAM 只负责把结构化请求稳定地转成 CST 产物和文件系统合同。

OpenClaw 集成方请直接阅读：[`docs/OPENCLAW_INTEGRATION.md`](docs/OPENCLAW_INTEGRATION.md)。

---

## 这个包对外提供什么

`leam` 是一个纯 Python 包，对外有 5 个入口：

| 接口 | 作用 |
| --- | --- |
| `build_and_simulate(request)` | 新建 / 复用一个 output 目录，跑 template 或 new 或 rerun 流水线 |
| `list_templates()` | 列出内置模板的元数据 |
| `get_project_context_snapshot(output_name)` | 只读：参数列表、最近一次仿真摘要、goal / 算法白名单 |
| `validate_optimization_request(request)` | 只读预检：goal 白名单、变量范围、单位归一 |
| `optimize_parameters(request)` | 在已存在的 `.cst` 工程上调用 CST Optimizer1D |

所有入口都能从 `leam` 顶层直接导入：

```python
from leam import (
    BuildAndSimulateRequest,
    OptimizationRequest,
    build_and_simulate,
    get_project_context_snapshot,
    list_templates,
    optimize_parameters,
    validate_optimization_request,
)
```

详细形状、错误码、文件产物合同见 [OPENCLAW_INTEGRATION.md](docs/OPENCLAW_INTEGRATION.md)。

---

## 关键设计原则

1. **无交互、无副作用**。所有 `input()` 路径已删除；预检 / 快照接口绝不 `mkdir`。
2. **结构化失败**。优化请求验证失败不抛异常，返回 `OptimizationResult(status="failed", error="validation_failed")`，具体错误码由 `validate_optimization_request` 给出。
3. **文件系统 = 单真相来源**。每个 output 目录根部写一份 `run.json`，OpenClaw 靠它恢复状态，不需要 SQLite。
4. **Goal 白名单**。OpenClaw 自然语言抽取出来的 goal 必须落到 `s11_min_at_frequency` / `bandwidth_max_in_band` / `resonance_align_to_frequency` 三选一；算法也有白名单。
5. **ParameterList 初始化与 VBA 历史分离**。优化前 Python 一次性写 `ParameterList`，VBA 历史只引用参数名，不再 `StoreParameters`——避免 Optimizer1D 的 trial value 被历史重建覆盖。

---

## 输出目录结构

每个 `output_name` 对应一个独立目录：

```text
examples/output/<output_name>/
├── run.json                           # OpenClaw 的入口清单
├── <output_name>.json                 # solids
├── <output_name>_parameters.bas       # ParameterList
├── <output_name>_dimensions.json
├── <output_name>_materials.bas
├── <output_name>_model.bas
├── <output_name>_boolean.bas
├── <output_name>.cst                  # 可选
├── results/
│   ├── manifest.json                  # 仿真状态
│   ├── simulation_audit.json
│   └── sparams/
│       ├── s11.s1p
│       └── s11.csv
└── results/optimization/
    ├── manifest.json                  # 优化状态
    ├── audit.json
    ├── best_parameters.json
    ├── history.csv
    └── parameters_optimizer_safe.bas
```

字段清单与 schema 版本：见 [OPENCLAW_INTEGRATION.md §7](docs/OPENCLAW_INTEGRATION.md#7-文件系统合同)。

---

## 安装

```bash
pip install -e LEAM-main
```

运行时依赖：

- Python 3.9+
- `openai>=2.0.0`（LLM 生成链路 + 模板匹配建议）
- CST Studio Suite（仅在调用 `build_and_simulate(run_cst=True)` 或 `optimize_parameters` 时）

### 配置

`leam` 会按以下顺序查找运行配置：

1. 环境变量：`OPENAI_API_KEY` / `CST_PATH`
2. `config.json`（示例见 `config.example.json`）

自检：

```bash
leam doctor
```

这是 `src/leam/cli.py` 里唯一的子命令，只做环境检查，不再启动任何交互式流程。

---

## 目录结构

```text
LEAM-main/
├── src/leam/
│   ├── __init__.py               # 顶层对外导出
│   ├── service_api.py            # OpenClaw 入口 dataclass + LeamService
│   ├── cli.py                    # leam doctor
│   ├── config.py
│   ├── workflows/                # new / template / rerun + contracts
│   ├── templates/                # 模板包（含 air_pifa）
│   ├── services/
│   │   ├── optimization_goals.py             # goal → VBA 翻译
│   │   ├── optimization_validation_service.py # NL → 结构化请求防线
│   │   ├── parameter_service.py
│   │   └── ...
│   ├── tools/                    # CST runner + VBA generator + parameter_vba
│   ├── infrastructure/           # cst_gateway + output_repository + run_record
│   ├── models/                   # SessionPaths / DesignSession
│   ├── core/                     # LLM caller + VBA generator
│   ├── prompts/                  # LLM prompt 资源
│   ├── resources/                # VBA / 建模参考资料
│   └── utils/
├── docs/
│   ├── OPENCLAW_INTEGRATION.md   # 集成手册（必读）
│   └── DEBUGGING_SUMMARY.md
├── examples/
│   ├── quickstart.py
│   ├── demonstration.ipynb
│   └── output/                   # 运行产物落地处
└── tests/                        # pytest 套件（64 项）
```

对外稳定符号都在 `leam.__init__` 的 `__all__` 中；直接从子模块 import 不保证稳定。

---

## 已删除的能力

相对旧版交互式 LEAM，本版裁掉了以下能力（改由 OpenClaw 承担）：

- `leam.app.run_cli()` / `cli_leam.py` 交互循环
- `leam.agent.*` 与相关 chat intent / memory 模块
- SQLite-backed session store
- 所有 `input()` 确认点（参数审阅、拓扑修订、CST 路径交互配置等）
- 自动化绘图 / S11 总结（由 OpenClaw 读 Touchstone 完成）

迁移提示：如果之前 import 过 `leam.app` / `leam.agent` / `leam.services.session_store`，全部需要迁移到 `leam.service_api`。

---

## 开发

```bash
cd LEAM-main
python -m venv .venv
.\.venv\Scripts\Activate.ps1       # Windows
# source .venv/bin/activate         # POSIX
pip install -e .
pip install -r requirements.txt

pytest tests -q
```

单元测试共 64 项，覆盖 service facade 路由、优化器白名单、NL → 结构化请求防线、`run.json` 写读、VBA 注释剥离等。

---

## License

MIT，详见 `LICENSE`。
