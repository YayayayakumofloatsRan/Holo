# Kernel v3 Deep Agent Loop Reimplementation 2026-06-17

状态：第一阶段代码落地；单 agent 深循环合同继续收紧；工具调用基础层开始成熟化；结构测试通过；未运行金融 live benchmark，不能报告为金融准确率。

## 1. 触发原因

本轮用户明确暂停继续小修补，要求分析本地 TypeScript agent loop 源码：

`D:\COURSES\人工智能算法实践\code-main\code-main`

WSL 路径：

`/mnt/d/COURSES/人工智能算法实践/code-main/code-main`

该源码 README 标注为 Claude Code source snapshot for security research，
没有可直接复用的 LICENSE/package 信息。因此本次采用“架构吸收、自主实现”的路线：
不复制源码；在 Holo Kernel v3 中用 Python 重新实现合适的 agent loop 机制。

2026-06-17 后续用户进一步明确：暂时不做多 agent 系统，先把单个 agent 的
通用循环做好。多 agent 不是当前瓶颈；当前瓶颈是单 agent 是否有足够稳定的
工具合同、结果反馈、错误恢复和上下文状态迁移。

## 2. 从外部 loop 吸收的核心设计

本次只吸收架构，不搬运代码：

- 一次 assistant turn 可以产生多个 tool calls，而不是每轮只能产生一个 action。
- 工具结果必须以 observation/tool-result 形式完整回流给下一轮模型，失败也不能只留在宿主日志。
- 工具有统一合同：名字、参数 schema、权限、side effect、可并发性、结果映射和上下文回填。
- read-only / network 类工具可以按批次组织；只有工具 manifest 显式声明 `concurrency_safe: true` 时才并发执行，write / shell / destructive 类工具独占执行。
- loop 状态迁移要可 journal、可观察、可恢复，不能把关键中间状态藏在内部函数里。
- 工具失败、权限拒绝、预算触顶都应成为模型可见的下一轮输入，而不是被 host 静默改写成规则分支。
- 模型发出的坏工具调用也要回流为 synthetic tool result，让模型下一轮可以修正，而不是被 host 静默丢弃。
- 工具发现应是模型可调用能力，而不是只靠 prompt 里塞固定工具清单。
- 工具执行需要 ToolUseContext，将 task/run/step/thread/tool_call_id/policy/allowed tools 作为稳定上下文传入工具。
- 工具执行层应事件化：queued / started / completed 能写入 journal，后续才能接 provider streaming。
- 长工具结果必须做预算化投影：模型上下文看结构、短 preview、截断状态和 artifact refs，完整 payload 留在 artifact/journal 边界内。
- 模型必须能按需读取 host 暴露的 artifact refs；否则 projection 只是摘要，无法支持复杂二次分析。
- 取消语义必须显式：pending sibling 可以取消，running tool 不假装可被 host 强行中断。

这些设计与 Holo 的不变量兼容：model proposes，host validates / executes /
journals / verifies。

## 3. 本次自主实现内容

新增：

- `kernel_v3/tool_use.py`
  - `ToolUseContext`
  - `ToolExecutionEvent`
  - `ToolResultProjection`
  - `StreamingToolExecutor`
  - `tool.discovery`
  - `artifact.read`
  - `register_tool_discovery`
  - `register_artifact_tools`

- `kernel_v3/deep_loop.py`
  - `AssistantTurn`
  - `ToolCallRequest`
  - `ToolCallParseError`
  - `ModelAssistantTurnPlanner`
  - `DeepAgentLoopController`
  - `assistant.turn` JSON 回合协议

接入：

- `kernel_v3/agent/runtime.py`
  - 支持 `agent_loop.runtime_backend = deep_agent_loop`
  - deep backend 下 model planner 改用 `ModelAssistantTurnPlanner`
  - deep backend 优先于 LangGraph backend
  - retrieval/workspace recipes 默认暴露 `tool.discovery`
  - retrieval/workspace recipes 默认暴露 `artifact.read`
  - registry 构建完成后统一挂载 tool discovery 和 artifact read

- `kernel_v3/agent/execution_profile.py`
  - `finance-capability` 默认切到 `deep_agent_loop`
  - `finance-fact-fast` 暂时保留 `langgraph` 快速通道

测试：

- `tests/test_kernel_v3_deep_agent_loop.py`
  - 验证同一 assistant turn 批量执行两个 read-only tools
  - 验证工具结果保留 `tool_call_id`
  - 验证工具执行收到标准 `ToolUseContext`
  - 验证工具执行事件写入 journal
  - 验证 malformed tool call 变成失败 observation 并允许下一轮重规划
  - 验证 batch observation 回流 journal
  - 验证 terminal final answer 路径

- `tests/test_kernel_v3_tool_use.py`
  - 验证 `tool.discovery` 返回当前允许工具的 manifest 合同
  - 验证 `artifact.read` 返回 bounded preview / bounded text body

- 更新：
  - `tests/test_kernel_v3_langgraph_loop.py`
  - `tests/test_kernel_v3_execution_profile.py`

## 4. 当前能力边界

第一阶段已经实现：

- 模型回合级多工具调用合同。
- 模型可调用 `tool.discovery` 发现当前允许的工具合同、side effect 和输入 schema。
- 模型可调用 `artifact.read` 根据 artifact ref 读取 bounded preview 或 bounded text body；默认 preview，只有 projection 不足时才用 mode=read。
- 工具调用转 `CandidateAction`，继续走 `PolicyGate` 和 `ToolRegistry`。
- 每次真实工具执行都会携带标准 `ToolUseContext`，工具能看到 task/run/step/thread/tool_call_id/policy/allowed tools。
- 每个工具调用都有稳定 `tool_call_id`，并贯穿 action / policy_decision / observation journal。
- 每个批次额外生成 `tool_batch_result` observation，供 evaluator 和下一轮上下文使用；batch 中逐项保留 `tool_call_id`、tool name、status、kind、observation_id、artifact refs、短内容预览和预算化 `content_projection`。
- `content_projection` 包含 preview、preview_chars、truncated、estimated_chars 和结构 shape，避免长 SEC/table 工具结果把模型上下文挤爆。
- `ContextPackCompiler` 对 `tool_batch_result` 使用专门 compact：下一轮上下文保留 `tool_call_id/status/artifact_refs/content_projection`，不再携带长 `content_preview`。
- `artifact.read` 通过 `ArtifactStore` 读取 host-exposed artifact，mode=read 会记录 artifact read audit，并受 `max_chars` 限制。
- 金融开放组件的长结果已经开始主动落入 `ArtifactStore` blob：SEC/EDGAR、Docling、Trafilatura、OpenBB、DuckDB table query 返回给模型的是短 observation、结构摘要、`artifact_id` 和 `artifact.read` hint；完整 JSON payload 留在 artifact 边界内，避免 SEC/table/document/market payload 直接挤爆下一轮模型上下文。
- malformed tool call 不再静默丢弃或错误执行为空参数；它会变成 `tool_call_parse_error` observation，再进入下一轮 replanning。
- 工具执行层改为 evented `StreamingToolExecutor`；即使当前还是 completed assistant turn 输入，也会记录 queued / started / completed 事件，后续可接 provider streaming。
- `StreamingToolExecutor` 支持 pending sibling cancel 回调；当前 deep loop 已准备 `tool_call_cancelled` observation，但 running 工具不会被伪装成已中断。
- 工具按连续批次组织；`none/read/network` 且 manifest 显式声明 `concurrency_safe: true` 的工具才并发，其他工具串行。
- terminal turn 走 respond/final answer 路径。

第一阶段尚未实现：

- provider streaming 中途发现 tool_use 后立即启动工具；当前 provider 协议只有 `ProcessorProvider.run()`，`OpenAICompatibleProvider` 仍固定 `stream: false`，所以只是执行层事件化，尚未接模型流式 delta。
- per-tool progress event；当前已有 queued / started / completed，不含长工具内部进度。
- running sibling shell/network failure 的强中断；当前只支持 pending sibling cancel 语义，运行中的工具依赖自身 timeout/abort。
- 深循环专用金融 obligation graph / slot coverage gate。
- debug50 live benchmark 重新刷分。

## 5. 与旧 Holo loop 的区别

旧 `LoopControllerV3` / 第一版 `LangGraphLoopController` 的实际语义仍是：

`compile context -> planner.propose one CandidateAction -> policy -> execute one tool -> evaluator -> stop/continue`

新 `DeepAgentLoopController` 的语义变为：

`compile context -> assistant.turn -> zero/many tool calls -> policy/execute all -> tool results as observations -> evaluator/next turn`

这解决的是结构问题：FB/FQA 复杂题不应被强迫成“每次只做一个动作”的窄循环。
LLM 可以一次性组装工作台，host 则保持验证、权限、预算和 provenance 边界。

## 6. 验证

已运行：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_langgraph_loop.py tests/test_kernel_v3_execution_profile.py -q
```

结果：

`30 passed in 1.13s`

补充检查：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_phase2_permissioned_tool_plane.py tests/test_kernel_v3_finance_open_components.py::test_finance_research_profile_exposes_tool_surface_without_numeric_verifier tests/test_kernel_v3_finance_engine.py::test_agent_context_compiler_injects_compact_toolchain_state_for_model_planner -q
```

结果：

`18 passed in 0.90s`

2026-06-17 后续补充验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_open_components.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_phase3_context_compiler.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase2_permissioned_tool_plane.py tests/test_kernel_v3_finance_open_components.py::test_data_table_query_writes_full_payload_artifact_when_store_is_available tests/test_kernel_v3_finance_engine.py::test_agent_context_compiler_injects_compact_toolchain_state_for_model_planner tests/test_kernel_v3_langgraph_loop.py -q
```

结果：

- `23 passed in 2.42s`
- `12 passed in 0.33s`
- `18 passed in 1.47s`

说明：这是结构/连通性测试，不是金融 benchmark 成绩。任何金融能力声明仍必须来自在线 live run，且 gold/reference 不进入模型上下文。

## 7. 2026-06-18 streaming workbench follow-up 修复

2026-06-18 的 follow-up 记录见：

`docs/KERNEL_V3_AGENT_LOOP_FOLLOWUP_2026-06-18_ZH.md`

新 live 探针显示：`financebench_id_04672` 不是缺少金融判断，而是 streaming
路径绕过了已有的 workbench follow-up scaffold。workbench 已经指出缺的是
balance-sheet net PP&E，slot binder 也拒绝了错误的 cash-flow PP&E purchase
候选，但主循环继续重复 `artifact.read`，没有把缺槽信号转成下一轮
`retrieval.run`。

本轮已修复：

- `DeepAgentLoopController` 在尝试 provider streaming planner 之前，先检查
  `retrieval_workbench_followup` feedback；如果 workbench 给出下一步 query /
  target document / source family，则直接 scaffold `retrieval.run`，仍走 host
  policy、tool registry、journal 和 observation 边界。
- `WorkloopConfig` 新增 `repeated_artifact_read_limit = 3`，同一 artifact/mode/
  max_chars 重复读取三次时产生 `same_artifact_read` repetition signal。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase61_workloop.py -q
```

结果：

- `21 passed in 3.20s`
- `31 passed in 9.28s`

本轮尝试对 `financebench_id_04672` 做 live 单题复测，但两次联网/live 命令均在
sandbox escalation 自动审核阶段超时，命令未启动。因此这次只记录为 agent
loop 合同修复，不记录为 FinanceBench 准确率提升。

## 8. 下一步

下一步不应再回到逐题补丁，而应沿 deep loop 补齐：

- `assistant.turn` prompt 的金融工具暴露质量。
- 将 provider streaming delta 接入 `StreamingToolExecutor`，实现模型边输出 tool_use，host 边启动工具。
- 长工具内部 progress event 和 abort token。
- tool discovery 结果的排序/分组进一步按 finance task family 优化，但不能做题目规则打表。
- SEC/EDGAR、XBRL、calculator、slot_bind、numeric verifier 作为同一种 ToolCallRequest 接口暴露。
- FinanceBench debug50 按题型分组跑 live 调试，失败必须归因到 loop/tool/prompt/verification 的通用缺口。

## 9. 2026-06-18 tool-result context modifier 补齐

用户再次强调：优先照搬成熟 agent loop 的实现思想，不要继续自研零散补丁。
本轮重新对照本地 TypeScript 项目的工具编排层，关键差异不是语言，而是成熟
loop 把 tool result 当成下一轮上下文修改器：

- 工具调用不是一次性输出；工具执行时携带 `ToolUseContext`。
- 工具结果可以产生 context modifier / next action。
- 下一轮 planner 看到的是已经被工具结果更新过的工作状态。
- loop 必须根据工具结果继续行动，不能只把结果写入日志供事后展示。

Holo 已经有 `StreamingToolExecutor`、`ToolUseContext`、`tool.discovery` 和
`artifact.read`，但 live trace 暴露出一个 P0 缺口：`finance.slot_bind`
已经能声明 `missing_slots` 和 `next_action`，主循环却没有稳定把这个信号转成
下一轮工具调用。典型失败是 `financebench_id_04672`：slot binder 判断缺少
balance-sheet net PP&E，并建议继续检索，但 loop 在 streaming 路径里继续重复
读取 artifact。

本轮补齐：

- `finance_working_state` 现在把 latest `finance.slot_bind` 的 `missing_slots`
  纳入统一缺槽集合，并把 `slot_bind.next_action` 暴露到 workbench state。
- `_RecipeEvaluator` 在 retrieval/finance 模式下，如果 slot_bind 声明
  `missing_slots + next_action` 且 numeric verification 尚未通过，会返回
  `finance_slot_bind_followup` feedback，阻止 premature final。
- `DeepAgentLoopController` 的 follow-up 入口从单一 workbench scaffold 扩展为
  `tool_result_followup_scaffold`：先处理 `finance_slot_bind_followup`，再处理
  `retrieval_workbench_followup`。
- `finance_slot_bind_followup` 不替模型选择事实或答案，只执行模型已经声明的
  `next_action`。当 next action 是 `retrieval.run` 且模型只给出 reason/missing
  slots 时，host 只组装检索 payload，让检索仍走正常 policy/tool/journal 边界。
- 增加重复 query 保护，避免同一 slot_bind follow-up query 循环执行。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase61_workloop.py -q
```

结果：

- `23 passed in 3.44s`
- `298 passed in 8.72s`
- `31 passed in 9.02s`

说明：这是 agent loop 合同修复，证明 tool result 能驱动下一轮工具调用；不是
FinanceBench/FinQA/live accuracy 成绩。金融指标仍必须来自在线 live run，且
gold/reference 不进入模型上下文。

## 10. 2026-06-18 final synthesis budget rebuild

用户再次强调：优先照搬成熟 agent loop 的实现，不要继续围绕单题小修小补。
本轮继续对照本地 TypeScript 项目的成熟 loop 思路，重点吸收其中一个通用
机制：当一个 streaming attempt / provider fallback / 工具结果路径不可继续时，
不要让旧 attempt 的残缺上下文污染下一轮，而要重建一个受控的新上下文包。

Holo live 探针暴露出的同类问题发生在 final synthesis：

- `financebench_id_03029` v1 live run 已经成功检索到目标 SEC 证据；
- `retrieval.run` 返回成功，目标 source URL/source family/required slots 都命中；
- journal 中已有 `395` 个 finance facts、claim ledger、slot frame、transform plan；
- 但 `synthesizer.answer` 首轮 prompt 达到约 `267,737` chars，超过
  `finance-fact-fast` 的 `max_prompt_chars_per_call=260,000`；
- fabric 直接返回 `processor_budget_exceeded`，repair retry 仍然用同类大包，
  最终输出 failure report，评分为 `failure_report_not_final_answer`。

这不是金融知识错误，而是成熟 agent loop 的上下文预算合同错误：工具和
workbench 已经完成了工作，但 finalizer 没有把工作状态压缩成 provider 可持续
消费的 packet。

本轮修复：

- `Synthesizer.synthesize(...)` 在调用 provider 前先构造 prompt 并读取
  `processor_budget.max_prompt_chars_per_call`。
- 如果 prompt 超出预算，会重建 compact synthesis packet，而不是把同一个大
  prompt 送入失败/repair 循环。
- compact packet 会按预算 profile 收缩 evidence、citations、finance fact
  ledger、candidate facts、FormulaTrace、trace support、competing clusters、
  metric hints、question numeric premise hints、search/fetch summaries 和预览长度。
- provider request parameters 会记录
  `synthesis_context_compaction=budgeted`、原始/压缩 prompt chars、压缩 profile、
  原始/压缩 evidence/citation 数量。
- `retrieval_report.diagnostics.synthesis_budget_compaction` 会进入模型 prompt，
  明确告知模型：语义判断仍由模型完成，host 只做预算化证据投影。
- JSON repair、unknown reference repair、missing citation repair 也走同一
  budgeted prompt 构造，避免 repair 分支重新膨胀。

这仍然不是规则答题，也不是按 benchmark id 打表。host 只控制证据包大小、
引用集合和 provenance 边界；最终答案、事实选择、限制说明仍由
`synthesizer.answer` LLM 输出。

结构验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_processor_streaming.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py::test_finance_fact_context_exposes_question_numeric_premise_hints_to_synthesizer_prompt tests/test_kernel_v3_finance_engine.py::test_finance_formula_trace_support_links_traces_to_fact_citations_in_synthesizer_prompt tests/test_kernel_v3_finance_engine.py::test_finance_fact_context_exposes_competing_clusters_to_synthesizer_prompt -q
```

结果：

- `108 passed in 6.05s`
- `3 passed in 0.59s`

新增结构测试 `test_phase5_synthesizer_compacts_prompt_before_processor_budget_limit`
证明：大 evidence/citation/fact-ledger packet 会在 provider 调用前压缩到
processor budget 内，并且 compaction metadata 会写入 processor request。
这是代码合同测试，不是金融能力成绩。

live 验证：

```text
.state/kernel_v3/bench/finance/run_fb_debug_o000_l001_live_20260618_streaming_v2.jsonl
.state/kernel_v3/bench/finance/run_fb_debug_o000_l001_live_20260618_streaming_v2.summary.json
```

同一 `financebench_id_03029` live 单题从 v1 的
`failure_report_not_final_answer / processor_budget_exceeded` 变为：

- status: `passed`
- score reason: `numeric_within_tolerance`
- answer: `3M FY2018 capital expenditure (Purchases of property, plant and equipment) was $1,577 million (USD millions).`
- tokens: `112,180`
- processor errors: none
- `synthesizer.answer`: 1 call, `57,262` prompt tokens, status ok
- citation present: true
- numeric verifier / verifier gate / synthesis gate: passed
- matched numeric: `1577.0`

这是有效 live 单题回归，证明 final synthesis budget rebuild 修复了此前的
budget-failure loop；它不是 debug50、test100、FinanceBench 总成绩，也不代表
可以跳过类型簇 live debug。
