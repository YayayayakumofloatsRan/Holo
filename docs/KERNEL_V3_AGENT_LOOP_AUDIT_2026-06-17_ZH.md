# Kernel v3 2026-06-17 Agent Loop Logic Audit

记录时间：2026-06-17 CST +0800  
分支：`kernel-v3`  
状态：逻辑审查、边界收紧、LangGraph-backed loop 第一阶段已落地；未启动 live benchmark。

## 1. LangChain / LangGraph 关系澄清

当前 Kernel v3 已开始把核心 agent loop 迁移到 LangGraph。第一阶段落地方式是：

- `finance-*`、`web-research`、`long-mission` execution profile 默认写入 `agent_loop.runtime_backend = "langgraph"`。
- `AgentRuntime` 根据 recipe metadata 选择 `LangGraphLoopController`。
- `LangGraphLoopController` 用 `StateGraph` 承载循环状态迁移和 in-memory checkpoint。
- Holo 的 `PolicyGate`、`ToolRegistry`、Journal、budget guard、verifier/gate 仍作为 graph node 内的 host-owned 边界。
- 没有 LangGraph 或没有显式 backend metadata 的旧路径仍 fallback 到 `LoopControllerV3`，用于兼容和对照。

实际 active finance profile 运行路径现在是：

```text
LangGraph StateGraph
  node prepare_and_execute:
    ContextCompiler -> Planner/model planner -> PolicyGate -> ToolRegistry
    -> Observation + Artifact journal
  node evaluate_and_route:
    post-observation ContextCompiler -> _RecipeEvaluator + WorkloopEvaluator
    -> StopController / result / failure report / continue edge
```

`langgraph==1.2.5` 已安装并已成为 finance profile 的 active loop backend。
`langchain-core==1.4.7` 已显式纳入依赖，用于后续对齐 LangChain 的
Runnable/tool/schema 接口层。完整 `langchain` 包当前未安装，不能汇报成已经
采用完整 LangChain Agent 生态。更准确的表述是：

- LangGraph：已用于 active loop backend 的第一阶段迁移。
- LangChain core：已用于接口生态依赖基座，下一阶段接 Runnable/tool/retriever 标准层。
- Holo：仍拥有权限、journal、预算、验证、gold isolation 和最终停止边界。

迁移原则不是让 LangChain/LangGraph Agent 直接替代 Holo，而是把 Holo 的不变量包装成成熟框架节点，逐步淘汰自研控制流。

## 2. Loop 必须满足的不变量

1. Planner 只能提出 action，不能执行 action。
2. 每个 action 执行前必须经过 `PolicyGate`。
3. 每个工具调用必须通过 `ToolRegistry`，不能在 planner/evaluator 中旁路执行。
4. Runtime controller 不能按具体金融工具名写分支；领域逻辑属于 recipe/evaluator/tool manifest/finance substrate。
5. 每步执行前编译 planner context；工具 observation 写入 journal 后，再重新编译 evaluator context。
6. Budget guard 必须在执行前阻止确定会越界的 action。
7. Tool observation 是模型重规划输入，不是 host 语义结论。
8. 可恢复组件失败进入 replan；policy、权限、预算和安全 guard 保持 host-owned 阻断。
9. Gold/reference 只允许 post-run scoring，不能进入 prompt、tool、retrieval 或 memory。
10. Final answer 必须经过 evidence/citation/numeric/synthesis gate；fake/offline tests 不能作为金融能力证据。

## 3. 本次审查修正

### 3.0 LangGraph-backed loop 第一阶段

新增 `kernel_v3/langgraph_loop.py`：

- `LangGraphLoopController` 继承 Holo 的边界方法，但用 LangGraph `StateGraph` 承载循环。
- graph node `prepare_and_execute` 负责 context、planner、policy、tool、observation。
- graph node `evaluate_and_route` 负责 post-observation context、evaluator/workloop、termination/continue route。
- 使用 LangGraph `MemorySaver` 做第一阶段 in-memory checkpoint。
- graph invocation 按 recipe `max_steps` 设置 `recursion_limit`，避免成熟 runtime 默认递归限制截断长任务。

回归覆盖：

- `test_langgraph_loop_controller_executes_holo_policy_tool_evaluator_path`
- `test_finance_execution_profile_selects_langgraph_loop_controller`
- `test_plain_recipe_keeps_holo_loop_controller_without_langgraph_metadata`

### 3.1 网络预算执行前越界检查

审查发现 `max_network_fetches` 过去只检查“已用 network fetches 是否达到上限”，没有检查“本次 action 的预计 fetch 成本加上已用量是否会越界”。

已修正为 projected-cost guard：

```text
if network_fetches + requested_network_fetches > max_network_fetches:
    block before tool execution
```

这保证声明成本已经超过剩余预算的 network action 不会进入工具执行层。回归覆盖：

- `test_loop_max_network_fetches_guard_blocks_projected_budget_overrun_before_execution`
- `test_phase61_network_budget_does_not_preempt_tool_observation_when_budget_remains`

### 3.2 Evaluator 使用 post-observation context

Loop 当前会在 observation 写入 journal 后重新编译 context，再交给 evaluator。这是正确方向：evaluator 必须看到刚发生的 observation、artifact、tool failure、citation 和 trace，而不是 planner 的旧上下文。

旧测试已更新为检查：

- planner context 是 action 前状态；
- evaluator context 是 observation 后状态；
- 两者 section 结构一致，但 context hash 不应相同。

### 3.3 可恢复工具失败回到模型重规划

金融工具链扩展后，Docling/OpenBB/Trafilatura/DuckDB/SymPy/SEC 等组件可能出现依赖缺失、组件调用失败、URL 不支持、SQL 被拒、route 不在 allowlist 等情况。之前 generic evaluator 会把这些 `failed/blocked` observation 直接变成终局失败。

已新增 recoverable toolchain failure replan：

```text
tool failure observation
  -> _tool_failure_can_replan
  -> Feedback(status="continue", missing_evidence=["tool_failed_replan", ...])
  -> planner sees failed tool diagnostics
  -> model chooses another source family/tool path
```

`policy_block` 不进入这个通道，避免绕过权限和安全边界。

### 3.4 Provider prompt 的 one-shot 工具接口完整性

审查时发现一个实际发包边界问题：runtime `_planner_directive()` 已经列出
SEC/EDGAR、Docling、Trafilatura、OpenBB、DuckDB、SymPy、calculator、
workspace、shell/script 等工具，但 `kernel_v3/processors/adapters.py` 的
provider compact 过去只保留前 6 个 `tool_selection`。这会造成 Holo 内部
“允许调用”，但真实模型首包看不到完整接口，削弱 one-shot 工具选择能力。

已修正为：

- provider compact `tool_selection` 非轻量路径保留 24 项，覆盖当前 finance open tool surface；
- `allowed_tools` / `executable_tools` 上限提高到 48；
- provider prompt 携带 `tool_selection_count`，用于发现被截断风险；
- provider prompt 携带 `toolchain_install_summary`；
- provider prompt 携带 compact `llm_first_finance_template.standard_tool_interface`，让模型知道标准 `planner.propose` 工具调用协议。

新增回归覆盖：

- `test_finance_capability_provider_compact_preserves_one_shot_tool_surface`
- `test_finance_capability_planner_directive_preserves_full_open_tool_surface`

## 4. 当前结论

当前系统已经从“只参考 LangGraph”推进到“finance/web/long profile 实际使用 LangGraph-backed loop”。这还不是完整 LangChain/LangGraph 化，但方向已经切换：成熟框架承载状态图，自研部分退到 host 边界、domain verifier、journal 和 benchmark isolation。

短期还需要继续推进：

- 把 `LoopControllerV3` 的重复控制流继续下沉/删除，保留为 fallback 或边界 mixin；
- 引入完整 LangChain 包或 LangChain-compatible adapter，统一 model/tool/retriever/document/Runnable 接口；
- 把 retrieval、finance toolchain、memory、observability 继续拆成 LangGraph nodes/subgraphs；
- 把 checkpoint 从 in-memory 推进到 durable persistence；
- 保持 gold isolation、policy、budget、verifier gate 不被框架抽象稀释。
