# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - OpenClaw 后端化重构（破坏性）

LEAM 从带聊天循环的交互式 CLI 裁剪为 OpenClaw 的无交互后端服务。OpenClaw 负责对话、记忆、意图识别、S 参数总结、多轮迭代；LEAM 只暴露结构化执行接口。

### 新增

- `leam.service_api`：OpenClaw 入口层，包含 `LeamService` 与对应 dataclass。
  - `build_and_simulate(request)`：自动分派 template / new / rerun 流水线。
  - `list_templates()`：列出内置模板元数据。
  - `get_project_context_snapshot(output_name)`：只读，返回 ParameterList、最近一次仿真摘要、goal / 算法白名单、`schema_hint`，供 OpenClaw 注入 LLM prompt。
  - `validate_optimization_request(request)`：结构化预检，绝不抛异常、绝不 mkdir。
  - `optimize_parameters(request)`：在已构建的 `.cst` 工程上调用 CST Optimizer1D；验证失败时返回 `OptimizationResult(status="failed", error="validation_failed")` 而不是抛异常。
- `leam.services.OptimizationValidationService`：NL → 结构化请求防线。
  - Goal 模板白名单（`s11_min_at_frequency` / `bandwidth_max_in_band` / `resonance_align_to_frequency`）。
  - 算法白名单（Trust Region Framework 等 6 种）。
  - 单位归一（`frequency_mhz` / `frequency_hz` / `freq_start_khz` → GHz）。
  - 参数名白名单：从 `<name>_parameters.bas` 解析 ParameterList 交叉校验。
  - 结构化错误码，详见 `docs/OPENCLAW_INTEGRATION.md` §6。
- `leam.services.optimization_goals`：Goal 模板 → `Optimizer1D` VBA snippet 翻译器。
- `leam.tools.parameter_vba.strip_parameters_store_call`：生成去掉 `StoreParameters names, values` 的 optimizer-safe 副本，避免 CST 历史重建时覆盖 trial value。
- `leam.infrastructure.run_record`：每个 output 目录根部写一份 `run.json`（schema `"1.0"`），作为 OpenClaw 恢复状态的单真相来源。
- `results/optimization/` 子目录：`manifest.json` / `audit.json` / `best_parameters.json` / `history.csv` / `parameters_optimizer_safe.bas`。
- `docs/OPENCLAW_INTEGRATION.md`：OpenClaw 集成的权威文档，包含 API 参考、错误码表、文件合同、模板约定、FAQ。

### 变更

- `CstRunner` 扩展：`store_parameter` / `store_parameters` / `get_parameter` / `configure_optimizer` / `run_optimizer`。优先走 CST Python API，不可用时退回 VBA。
- `CstGateway.run_optimization`：完整编排优化流程——读 seeds、灌 ParameterList、重建 history（使用 optimizer-safe parameters BAS）、配置 Optimizer1D、同步运行、读回最优值、写 manifest / best_parameters / audit。
- `DesignSession` 与 `SessionPaths`：去掉聊天期书签字段（`pipeline_mode` / `topology_messages` / `last_geometry_plan`），新增优化产物路径属性。
- `TemplateRunner`：删除内部缓存与 `_confirm_fn` 交互层，改为"规则命中 → LLM top-1 建议 → None"。
- `cli.py`：仅保留 `leam doctor`，不再暴露 `chat` 子命令。

### 移除（破坏性）

- `leam.app` / `cli_leam.py` / `leam.ui.*`：交互循环、CLI 主入口、所有 `input()` 场景。
- `leam.agent.*`：ChatIntentService / MemoryManager / SessionStore 全部删除。
- `leam.services.chat_intent_service` / `memory_manager` / `session_store`：聊天 / 记忆层清空。
- `leam.services.design_intent_service` / `geometry_plan_service`：交互式设计意图服务。
- 所有涉及的 prompt 资源与对应测试。
- `OptimizationRequest` 验证失败不再抛 `ValueError` / `FileNotFoundError`，改为结构化 `OptimizationResult(status="failed")`。

### 迁移提示

- 原本 import `leam.app` / `leam.agent` / `leam.services.session_store` 的调用必须迁移到 `leam.service_api`。
- OpenClaw 侧应当改为读 `run.json` 而不是 SQLite。
- 原本依赖"交互式参数审阅"的工作流需要 OpenClaw 在调用前把改动写入 `OptimizationRequest.variables` / `BuildAndSimulateRequest.simulation_request`。

## [0.2.0]

- Updated the model usage from GPT-4o/o1 to GPT-5.2 with explicit reasoning effort options.
- Standardized inputs and outputs to Markdown and JSON to improve stability and readability.

## [0.1.0]

- Initial release.
