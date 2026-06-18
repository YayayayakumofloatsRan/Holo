# Kernel v3 Agent Loop Follow-Up 2026-06-18

状态：已完成多轮通用 agent loop 合同修复；结构测试通过；已有单题 live debug-row
证明 `sec.edgar.financials -> slot_bind -> calculator/formula_trace -> verifier/gate`
链路可闭合。该结果不是 debug50/test100 准确率。

## 1. 本轮触发

用户明确要求优先参考成熟 agent loop 的实现，不再围绕单题继续补丁。随后一轮 live FinanceBench debug 探针暴露出通用循环缺陷：

- `financebench_id_04672` 真实 live 失败，输出文件：
  `.state/kernel_v3/bench/finance/fb_debug50_stream_types_o001_l002_20260618.jsonl`
- 题目需要 3M FY2018 year-end net PP&E。
- 系统取得了 3M 2018 10-K PDF 和 SEC financials artifact，但 workbench 发现缺的是 balance sheet 的 net PP&E。
- 后续 streaming loop 反复 `artifact.read` 同一个 SEC/artifact payload，直到 `max_steps`，没有把 workbench 的缺槽信号转成新的可执行 retrieval action。
- 后处理中的 `finance.slot_bind` 正确拒绝把 cash-flow `Purchases of PP&E` 当成 balance-sheet net PP&E，但该 `needs_more_evidence -> retrieval.run` 信号没有回到主循环。

这不是 3M 题面特例，而是循环合同缺陷：工具结果、缺槽、下一步动作、重复检测没有形成强闭环。

## 2. 外部成熟实现给出的直接启发

本轮再次对照本地 TypeScript agent-loop 项目：

`/mnt/d/COURSES/人工智能算法实践/code-main/code-main`

可迁移的核心不是金融工具，而是运行语义：

- query loop 持有会话状态，而不是只持有单次动作；
- tool-use context 是工具执行的稳定上下文；
- streaming executor 负责 queued / executing / completed / cancelled 的工具状态；
- 每个 tool_use 都必须对应 tool_result，包括失败、取消、fallback；
- 工具结果不是直接堆进上下文，而是进入可压缩、可替换、可再次读取的工作台；
- 重复工具调用要进入调度约束，而不是等到步数耗尽。

## 3. 本轮代码修复

### 3.1 Streaming path 先执行 workbench follow-up

修改：

- `kernel_v3/deep_loop.py`

之前 `_workbench_followup_scaffold_turn(...)` 只在 non-streaming planner 分支之后执行。`finance-capability` live 使用 `--agent-loop-streaming` 后，这个保护完全绕过，导致模型继续读旧 artifact。

现在每一轮在尝试 streaming planner 之前，先检查上一轮 feedback 是否要求 `retrieval_workbench_followup`。如果 workbench 提供了 `next_queries` / `next_document_targets` / source families，host 会 scaffold 一个 `retrieval.run` 工具调用，并且仍然通过正常 policy、tool registry、journal、observation 路径执行。

该修复不选择答案事实，也不编码 benchmark 答案；它只执行上一轮 LLM workbench 已经提出的下一步检索路线。

### 3.2 artifact.read 重复检测

修改：

- `kernel_v3/agent/workloop.py`

新增 `WorkloopConfig.repeated_artifact_read_limit = 3`。同一 `artifact.read` 对同一 artifact/mode/max_chars 重复三次时，`detect_repetition(...)` 产生 `same_artifact_read`。

此前通用 `repeated_action_limit = 16` 高于常见 `max_agent_steps = 10/12`，因此 FinanceBench live 中的重复 artifact 读取永远不会在步数耗尽前被抓到。

## 4. 结构验证

本轮只报告结构测试，不报告金融准确率：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase61_workloop.py -q
```

结果：

- `21 passed in 3.20s`
- `31 passed in 9.28s`

新增覆盖：

- streaming planner 存在时，如果上一轮 feedback 要求 workbench follow-up，loop 会先执行 scaffolded `retrieval.run`，不会调用 streaming planner 去读旧 artifact；
- 默认三次重复 `artifact.read` 会形成 `same_artifact_read` repetition signal。

## 5. Live 验证状态

尝试对刚失败的 `financebench_id_04672` 做单题 live 复测：

```text
fb_debug50_stream_followup_o001_l001_20260618.*
```

两次联网/live 命令都在 sandbox escalation 的自动权限审核阶段超时，命令没有启动。因此本轮没有新的 live accuracy 结果。

结论必须保持严格：

- 可以声明：agent loop 结构缺陷已定位并完成结构修复，目标测试通过。
- 不可以声明：FinanceBench 准确率已经提升。
- 下一步仍需要一条 live 单题复测来确认 `financebench_id_04672` 是否从重复 artifact.read 进入正确 workbench follow-up retrieval。

## 6. 下一步

优先级仍是成熟 agent loop，而不是题目补丁：

1. 运行 `financebench_id_04672` 单题 live 复测，确认 streaming workbench follow-up 生效。
2. 若仍失败，检查直接 PDF/SEC URL 的 table/span extraction 是否能定位 balance-sheet net PP&E。
3. 将 `finance.slot_bind` 的 `next_action` 结果接回主循环，而不是只停留在后处理。
4. 把 artifact 工作台升级为字段级查询接口，减少整包 `artifact.read`。
5. 再按 debug50 类型簇做 live 调试，不做长回归，不做 fake accuracy。

## 7. Mature-loop trace parity checkpoint

用户继续要求优先照搬成熟 agent loop 的实现思想。本轮重新对照本地
TypeScript 项目的 `QueryEngine` / `queryLoop` / `StreamingToolExecutor`：
成熟实现不是只把工具结果写进日志，而是把 assistant turn、tool use、
tool result、feedback、恢复/继续状态组成下一轮模型可见的稳定轨迹。

本轮补齐：

- `ContextPackCompiler` 新增预算感知 `agent_trace` section，保留最近的
  assistant turn、action、非普通 allowed policy block、tool execution event、
  observation、feedback、guard、result 的模型可见轨迹。
- `agent_trace` 不复制完整工具结果；observation 在 trace 中只保留索引式
  outline，详细工具结果仍由 `recent_observations`、`ArtifactStore` 和
  `artifact.read` 承担，避免上下文重复膨胀。
- `agent_trace` 会过滤低价值 progress event 和普通 allowed policy decision，
  保留影响下一步推理的记录；小预算 context 自动关闭或缩小 trace 窗口。
- `_assistant_turn_prompt(...)` 将 `agent_trace` 从 sections 中提升为显式
  `context.state.agent_trace`，让模型 one-shot 下一步工具调用时能直接看到
  最近 tool_call_id、工具名、状态、feedback 和 artifact 引用。
- `ProcessorFabric` 的 provider availability circuit 已从 provider 级改为
  provider+model 级。一个 DeepSeek pro timeout 不再把同 provider 的 flash
  synthesizer/slot_bind 一并短路，避免单模型故障破坏后续 loop 恢复。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase1_context_trace.py tests/test_kernel_v3_phase3_context_compiler.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_provider_native_tools.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase5_semantic_processors.py::test_phase5_processor_fabric_short_circuits_repeated_provider_availability_failure tests/test_kernel_v3_phase5_semantic_processors.py::test_phase5_provider_circuit_is_scoped_by_model_not_whole_provider tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_processor_streaming.py -q
```

结果：

- `24 passed in 3.32s`
- `22 passed in 0.54s`
- `18 passed in 0.87s`

说明：这是通用 agent loop 成熟度修复，不是 FinanceBench/FinQA 准确率成绩。
本轮没有新增可报告的 held-out finance benchmark 分数。下一步应继续用 live
debug50 类型簇验证：模型是否能利用 `agent_trace` 和工具 surface 自主恢复失败、
补齐证据、计算并通过 verifier。

## 8. Mature-loop executor/tool-surface parity checkpoint

用户再次强调优先照搬成熟 agent loop，而不是继续自研低层循环。本轮继续对照
本地 TypeScript 项目的 `queryLoop`、`Tool`、`StreamingToolExecutor`、
`toolOrchestration` 和 `toolSearch`，把两项通用运行语义补进 Holo：

- `StreamingToolExecutor` 新增有界并发，默认同批 concurrency-safe 工具最多
  10 个 worker，而不是按批大小无限启动；`started` 事件现在由 worker 真正
  开始执行时发出。
- 工具失败是否取消 sibling 不再是全局布尔值。`DeepAgentLoopController` 现在
  只让 shell/write/destructive 或非只读独占工具失败触发 pending sibling
  cancel；普通 read/network 工具失败保留其他独立工具结果，避免复杂研究题里
  一个网页/SEC 查询失败就误伤同批计算、文档读取和检索。
- `assistant.turn` prompt 新增 `tool_surface` 合同：visible/always-load 工具
  暴露 compact `input_schema`、runtime、权限和 side-effect；deferred 工具只
  暴露 brief，并明确要求模型通过 `tool.discovery` 获取完整 schema。
- 该工具面来自 host registry 的 `ToolManifest` 和 `ToolRuntimeSpec`，仍保持
  “模型选择，host 校验/执行/记录”的边界；没有新增金融题面规则，也没有任何
  benchmark 答案表。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_tool_use.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_phase3_context_compiler.py tests/test_kernel_v3_phase1_context_trace.py -q
```

结果：

- `25 passed in 3.27s`
- `9 passed in 0.22s`
- `15 passed in 0.34s`

说明：这是 agent loop/tool interface 成熟度修复，不是新的 FinanceBench、
FAB/FinAgent 或 FinQA 准确率。下一步应在 live debug50 类型簇上验证：模型
是否能利用显式 `tool_surface` 一次性构造更正确的 `sec.edgar.financials`、
`retrieval.run`、`document.*`、`calculator.compute` 和 `finance.slot_bind`
调用链。

## 9. Finance tool runtime/spec P0 checkpoint

继续审查后发现一个实际 P0 缺口：executor 已经具备成熟并发/取消语义，但
finance open-component manifest 基本没有 `ToolRuntimeSpec` hints，导致 SEC、
Docling、Trafilatura、OpenBB、DuckDB、SymPy、slot_bind、calculator、verifier
这些 read/network 工具在调度层仍可能被当成默认非并发工具。

本轮补齐：

- `calculator.compute`、`finance.verify_numeric`、`finance.slot_bind` 标记为
  `always_load`、read-only、concurrency-safe，并设置结果大小策略。
- `retrieval.run` 标记为 `always_load`、read-only、concurrency-safe、可取消，
  并保留 operator 是否真的 network-open 的 `open_world` 差异。
- SEC/EDGAR、Trafilatura、OpenBB、DuckDB、SymPy 工具补齐 read-only、
  concurrency-safe、timeout、result persistence 和 `always_load` hints。
- `document.docling.convert` 保持 read-only/always-load，但因 PDF/Docling 转换
  可能占用较高内存，显式标为非 concurrency-safe，并给出 120s timeout 与
  cancel hint，优先保护 UbuntuHolo 稳定性。
- `sec.edgar.financials` schema 新增 `fiscal_year` 和 `period/target_period`
  参数；工具只按请求期间过滤/投影 SEC 候选记录或列，不替模型选择 line item、
  formula 或最终结论。

这直接对应 live trace 中暴露的问题：FY2022/FY2024 类问题如果工具接口没有
期间参数，模型只能凭 statement 最近列猜，容易把 2023-2025 候选错当目标期间。
现在模型可以 one-shot 传入 `fiscal_year=2022` 或 `period=FY2024`，host 返回
更干净的候选集，但语义判断仍由 LLM 完成。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_phase3_context_compiler.py tests/test_kernel_v3_phase1_context_trace.py -q
```

结果：

- `79 passed in 7.76s`

说明：这是金融工具接口和 loop 调度成熟度修复，不是 FinanceBench/FQA/FAB 分数。
下一步仍需要 live debug50 类型簇验证这些 runtime/schema hints 是否让模型更少
走错期间、更稳定地组合 retrieval/SEC/document/calculator/slot_bind。

## 10. Mature-loop incremental executor checkpoint

用户再次指出应优先照搬成熟 agent loop 的实现，而不是继续自研低层循环。本轮
对照 TypeScript 项目的 `StreamingToolExecutor.addTool(...)`、
`getCompletedResults(...)`、`getRemainingResults(...)`、`discard(...)` 后，
发现 Holo 仍有一个结构性问题：non-streaming 工具批处理使用
`StreamingToolExecutor.execute_batches(...)`，但 provider streaming 路径在
`DeepAgentLoopController._execute_streaming_turn(...)` 内部另写了一套
`pending + ThreadPoolExecutor + wait_for_streaming_slot`。

这会造成同一个 agent loop 有两套并发/顺序/取消/超时语义。短期看像是某道
FinanceBench 题没做出，长期看是 loop 理论能力不稳：同一批工具在 JSON planner
和 native streaming planner 下可能有不同执行边界。

本轮补齐：

- `StreamingToolExecutor` 升级为真正的增量状态机，新增
  `begin_incremental(...)`、`add_item(...)`、`drain_completed(...)`、
  `finish_remaining(...)`、`discard()`、`close()`。
- `execute_batches(...)` 不再维护另一套批处理逻辑，而是复用同一个增量状态机。
- 增量 executor 保留成熟实现的核心语义：concurrency-safe 工具可并发启动；
  非 concurrency-safe 工具必须独占；exclusive 工具会阻塞其后的 safe 工具；
  结果在安全时可提前 drain；每个工具生命周期继续发出 queued/started/completed
  或 cancelled 事件。
- `_execute_streaming_turn(...)` 删除本地 pending future 调度，provider
  `tool_call_delta` 一旦形成完整工具调用，就通过同一个 executor 增量加入。
  这使 streaming 与 non-streaming 路径共享失败取消、超时、progress、事件记录
  和工具结果回收语义。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_tool_use.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_provider_native_tools.py -q
```

结果：

- `10 passed in 0.32s`
- `29 passed in 3.34s`

说明：这是 mature-loop 架构迁移，不是新的金融 benchmark 分数。它的意义在于
把工具调用 substrate 从“双路径实现”推进到“同一 executor 合同”，为后续
debug50 类型簇 live 调试提供更稳定的理论基础。

## 11. Live stability and convergence checkpoint

在增量 executor 迁移后，本轮继续做了一次真实 live 单题探针，仍使用
`financebench_id_04672`。该探针不是成绩，而是线上诊断；gold/reference 没有进入
模型上下文。

先暴露出一个稳定性问题：默认全局 journal 曾包含半截 JSONL 行，旧
`JournalStore` 初始化时一次性 `read_text(...).splitlines()` 并直接解析，导致
CLI 在 live 开始前因 `JSONDecodeError` 崩溃，也会对大 journal 带来不必要内存
压力。本轮将 journal 加载改为逐行流式读取，遇到损坏/半截行时跳过并记录
`load_warnings`，不再让历史 partial row 阻断新的 isolated live run。

随后使用 isolated journal 运行：

```text
.state/kernel_v3/bench/finance/fb_debug50_o001_l001_incremental_executor_journalfix_20260618.*
```

该 run 证明 streaming executor 和 workbench follow-up scaffold 能进入真实
`retrieval.run` 路径，但在 `--live-max-network-fetches 8` 下触发 host guard 后，
后续 evaluator 仍反复要求同一类 workbench follow-up。为避免 host 自动生成一个
它已经知道会被同一 guard 阻塞的动作，本轮让
`_workbench_followup_scaffold_turn(...)` 检查最近同一 workbench decision 之后
是否已经出现 `reason=max_network_fetches` 的 host guard。若出现，则不再自动
scaffold 同一 follow-up，而是把控制权交回模型重规划。这个修复不选择答案事实，
也不绕过 guard。

再用更高 fetch budget 做第二次真实 live 探针：

```text
.state/kernel_v3/bench/finance/fb_debug50_o001_l001_guardaware_20260618.*
```

该 run 被手动中断，没有产生 benchmark row，因此不能报告准确率。它暴露出更上层
的通用收敛问题：模型/工具链拿到了 3M Wikipedia 和错误期间的 3M 2018 PDF 后，
`document.docling.convert`、`sec.edgar.financials`、`shell.exec` 等工具结果混合
进入 fact/claim ledger；slot/target-document binding 能把这些错源打低分或拒绝，
但 final numeric repair 又触发新的 `task.compile`，导致上下文继续膨胀，而不是
压缩成“错源已排除、必须重新定位 FY2022 10-K/目标行项目”的工作台状态。

因此本轮真实 live 的结论是：

- UbuntuHolo 稳定性边界可控；内存保持稳定，失控前已手动中断。
- executor/tool surface 已向成熟 loop 靠拢，但还缺“错误证据隔离”和“工作台压缩
  后重规划”的上层合同。
- 下一步不能再围绕某个答案写题目补丁，应继续照搬成熟 agent loop 的状态机思想：
  tool result 进入可替换工作台，错源进入 rejected-evidence ledger，模型下一轮只
  看到必要 trace 和可调用工具，而不是完整错误事实洪水。

新增/回归结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_phase1_journal_store.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_tool_use.py -q
```

已覆盖：

- partial/corrupt JSONL row 不再阻断 journal store 初始化；
- incremental executor 在 streaming/non-streaming 路径共享并发和独占语义；
- workbench follow-up 在同一 network budget guard 后停止自动重复 scaffold。

## 12. Rejected-evidence workbench checkpoint

上一节 live probe 暴露的核心不是“3M 这道题怎么写规则”，而是成熟 agent loop 的
上下文管理缺口：错源证据被 target-document binding 打低分或拒绝后，仍然能作为
普通 `finance_fact_ledger` / `claim_ledger` 内容进入后续 task compile、repair 和
synthesis 上下文。成熟 TypeScript loop 的对应思想是：tool result 先经过
tool-result budget、microcompact、context collapse，再以可替换/可恢复的状态进入
下一轮，而不是把所有失败输出永久堆进模型窗口。

本轮把这个思想落到金融工作台：

- `finance_fact_ledger.primary_source_numeric_binding.rejected_candidates` 现在会被提升为
  一等 `finance_rejected_evidence_ledger`，并进入 `finance_working_state.rejected_evidence`。
- 当目标绑定明确 `primary_source_required=true` 且
  `primary_source_numeric_binding.status=no_binding_match` 时，working state 不再把这些
  rejected candidates 暴露为可用 `facts`；它们只出现在 rejected-evidence 状态中。
- 同一条件下，host 不再用 rejected candidates 生成后续 semantic task compile 输入，
  也不再从这些错源 facts 生成普通 finance claim ledger；而是写入
  `finance_evidence_replan_gate`，让下一轮模型重规划目标 filing/source/period/line item。
- `finance_working_state.workbench.current_phase` 增加 `evidence_replan`，并把
  `retrieval.run`、`sec.edgar.financials`、`document.docling.convert` 作为候选动作提示。
- `_RecipeEvaluator` 在看到最新 `finance_rejected_evidence_ledger` 且 primary-source
  no-match 时返回 `finance_rejected_evidence_replan` feedback，阻止 premature final。
- 市场估值类题不受该 gate 影响：只有显式 primary-source-required target binding 才会
  触发错源隔离；Yahoo/market-data EV/EBITDA 这类题仍可继续进入 formula trace 链路。

边界仍保持不变：host 只隔离已被 source contract 验证为不匹配的候选，不替模型选择
正确事实、公式或最终判断。模型仍然可以决定下一步检索、重新绑定、说明限制或最终回答。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_processor_usage.py -q
```

结果：

- `372 passed in 10.02s`

说明：这是 P0 agent-loop/workbench 成熟度修复，不是 FinanceBench/FinQA 新分数。
下一步应做小规模 live probe 验证：同类 primary-source 错源是否能从
`evidence_replan` 转向正确 filing/document 工具，而不是继续污染 fact/claim ledger。

## 13. Deep tool budget guard and trace budget checkpoint

在 rejected-evidence workbench 边界之后，又做了一次真实 live 单题诊断，仍然针对
`financebench_id_04672`。该 run 是线上诊断，不是成绩；gold/reference 没有进入模型
上下文。运行使用 isolated state：

```text
.state/kernel_v3/bench/finance/fb_debug50_o001_l001_rejected_evidence_20260618.*
```

本次诊断没有重现上一轮“错源 rejected candidates 污染普通 fact/claim ledger”的问题。
模型/工作台已经能把缺口收敛到 3M FY2022 filing、目标期间和 PP&E 等 primary-source
line item。但新暴露出更底层的成熟 loop 缺口：deep tool batch 内部已经出现 host guard
`reason=max_tool_calls`，而外层 `WorkloopEvaluator` 仍允许模型 evaluator 继续请求工具。
这说明预算 guard 只存在于 batch payload 里，没有被 termination layer 作为 host 级
终止信号识别。

本轮修复把 mature TypeScript loop 的 host-boundary 思想落到 Python loop：

- `decide_termination(...)` 现在能从普通 observation 和 deep
  `tool_batch_result.content.results[]` 中递归识别 `host_guard` /
  `loop_guard`，包括 `max_tool_calls` 和 `max_network_fetches`。
- 当 deep batch 已经命中 `max_tool_calls`，且当前并非可交付 final answer，host 会覆盖
  模型的 `continue` feedback，写出 `failure_report reason=max_tool_calls`。
- 当 deep batch 命中 `max_network_fetches`，若已有有效 citation/evidence，host 可交付
  partial-evidence final；否则同样输出 `failure_report reason=max_network_fetches`。
- `agent_trace` 上下文压缩增加最小投影：只保留最近 ID、工具名、状态、tool batch
  guard、feedback 缺口等 loop 恢复字段。若 section budget 仍不足，host 会显式省略
  `agent_trace`，而不是让 context compiler 抛 `BudgetExceeded` 中断循环。

这次改动仍然不是题目规则：host 没有选择财务事实、公式或答案，只是在预算和上下文
边界上保证 agent loop 不会在已经被 host 阻断的工具路径上继续空转。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_phase61_workloop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase61_workloop.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_processor_usage.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase1_journal_store.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_processor_streaming.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_phase61_workloop.py -q
```

结果：

- `32 passed in 8.95s`
- `430 passed in 23.53s`
- `483 passed in 33.15s`

剩余 P0 仍然清楚：继续对照成熟 agent loop，把 runtime progress/result 注入、动态
tool discovery、工具上下文替换和类型簇 live debug50 连接起来。下一次 live 不应再长
回归，而应按题型簇验证：工具路径是否能从 `evidence_replan` 进入正确 filing/source，
并最终稳定到 slot bind、calculator/formula trace、numeric verifier 和 synthesis gate。

## 14. Tool context update checkpoint

继续对照本地 TypeScript 项目的 `queryLoop` / `runTools`：成熟 loop 在工具执行后不只
把 tool_result 作为一条消息追加进去，还允许工具返回 `contextModifier`，由 loop 在
下一轮 API 调用前更新 `ToolUseContext`。这对 Holo 很关键：金融任务里的
`finance.slot_bind`、`retrieval.workbench`、`artifact.read`、`tool.discovery` 等结果，
应该能变成稳定的小型工作台提示，而不是只靠下一轮 context compiler 从大量
observation 中重新猜。

本轮实现了 Holo 版本的 host-owned contextModifier：

- `ToolResult` 新增兼容字段 `context_updates`，默认空列表；现有工具无需修改。
- `DeepAgentLoopController` 在工具执行后生成 `tool_context_update` ledger：
  - 工具显式返回的 `context_updates` 会被标准化为
    `schema=holo.kernel_v3.tool_context_update.v1`。
  - 普通 observation 若包含 `missing_slots`、`next_action`、`artifact_read_hint`、
    `content_replacement`、`tool_surface_schema`、`tools` 等通用上下文字段，也会生成
    一个派生 update。
  - 每个 deep `tool_batch_result.results[]` 记录 `context_update_refs`，保持 batch
    observation 与 context update 的可追溯关系。
- `ContextPackCompiler` 新增可选 `tool_context_updates` section，只暴露最近 4 条；
  小预算下只保留最近 2 条和紧凑 hints。它与 `agent_trace`、`recent_observations`
  分开，避免把大工具结果绕回 prompt。

边界：这不是让工具直接改 Holo 状态对象，也不是让 host 选择金融答案。update 只是
observation-derived hint，仍由模型决定下一步工具、语义绑定、公式和最终判断；host 只
负责标准化、记录、预算压缩和暴露。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_phase3_context_compiler.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_phase3_context_compiler.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_processor_streaming.py tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase1_journal_store.py tests/test_kernel_v3_phase3_context_compiler.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_processor_streaming.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_phase61_workloop.py -q
```

结果：

- `37 passed in 3.50s`
- `356 passed in 11.64s`
- `494 passed in 33.23s`

下一步仍应继续搬成熟 loop 的运行时能力：先补动态 token-aware tool expansion，再补
运行中 progress/result 注入同一 provider conversation，并按 debug50 题型簇做 live
验证。这些才会直接推动 FB/FQA 做题指标，而不是在单题上继续打补丁。

## 15. Context-aware tool expansion checkpoint

上一节完成了 Holo 版本的 contextModifier，但如果 provider-native 工具面仍然静态，
模型下一轮即使看到 `tool_context_updates` 里的 `next_action.tool`，也可能拿不到该
deferred tool 的 schema，只能再绕一次 `tool.discovery`。本轮继续对照成熟 loop 的
“按当前上下文刷新 tools”思想，把工具展开从固定清单推进到 context-aware。

实现：

- `openai_native_tool_surface(...)` 新增 `expand_tool_names`。当某个工具原本
  `should_defer=true`，但当前上下文明示需要该工具时，它会被临时放入 provider-native
  `tools`，而不是留在 `native_tool_deferred`。
- `ModelAssistantTurnPlanner` 从当前 `ContextBundle` 中提取显式工具请求：
  `tool_context_updates.hints.next_action.tool`、
  `finance_working_state.workbench.slot_bind_next_action.tool`、
  `next_action_options` 中形如 `retrieval.run` 的工具名，以及 `tool.discovery`
  返回的 `tools[].name` / `requested_tool_names`。
- `_assistant_turn_prompt(...)` 的 JSON prompt `tool_surface` 与 provider-native
  surface 使用同一组 context-requested tools。也就是说，JSON 模式和 streaming/native
  模式看到的可用工具合同保持一致。
- 增加 token-aware visible-tool 限额：低预算上下文只显示较少 schema；`always_load`
  和 context-requested tools 优先。超出 visible budget 的工具仍保留为 deferred summary，
  要求模型通过 `tool.discovery` 获取 schema。

边界：host 只根据结构化上下文中的显式工具名展开 schema，不从自然语言关键词猜工具，
也不替模型发起调用。模型仍然决定是否调用、如何组参、是否需要先发现工具、是否回答。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_phase3_context_compiler.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_processor_streaming.py tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase1_journal_store.py tests/test_kernel_v3_phase3_context_compiler.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_processor_streaming.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_phase61_workloop.py -q
```

结果：

- `34 passed in 3.36s`
- `359 passed in 11.67s`
- `497 passed in 33.24s`

剩余 P0 继续缩小：下一块应做运行中 progress/result 注入同一 provider conversation，
然后按 FB/FQA debug50 题型簇做 live 验证，而不是继续做长回归或单题补丁。

## 16. Provider tool-result continuation checkpoint

成熟 TypeScript loop 的另一个关键点是 tool_use 与 tool_result 在 provider conversation
里闭合：模型发出工具调用后，host 执行工具，再把 tool result 作为下一条消息送回同一
provider/model 会话，而不是只等外层 loop 重新编译上下文。Holo 之前已经能 streaming
执行工具，但工具结果只进入 journal/context，provider 本轮看不到结果。本轮补上这个
结构接口，并继续推进到有限多轮 continuation。

实现：

- `AssistantTurnStream` 新增 `provider_messages` 和 `continue_events` callback。
  `ModelAssistantTurnPlanner.stream_turn(...)` 初始请求仍走 provider-native tools；当
  deep loop 产生工具结果后，可以通过 callback 向同一 provider/model 发 continuation。
- `DeepAgentLoopController._execute_streaming_turn(...)` 在 streamed tools 执行完成后，
  组装 provider-compatible messages：
  - 原始 user prompt；
  - assistant tool_calls，其中 tool name 使用 provider 原始/native name，arguments
    使用 provider 原始 JSON；
  - 每个 tool 的 bounded `role=tool` result，内容为
    `holo.kernel_v3.provider_tool_result_message.v1`，只包含 observation id/status/source、
    content projection、artifact refs 和 host boundary。
- continuation stream 的文本会进入 deep `tool_batch_result.content.assistant_continuation`，
  evaluator 仍然决定是否 final；host 不把 continuation 文本直接当作金融正确答案。
- 如果 continuation 再次返回 provider-native `tool_call_delta`，现在不再当作
  `tool_call_delta_after_tool_result_continuation` parse error，而是回到同一个 streaming
  解析/执行状态机：解析工具名和原始参数、走 policy/budget/timeout、执行工具、写
  observation，然后把新的 bounded tool result 再追加进同一个 provider conversation。
- 每次注入写入 `provider_conversation_update` ledger，记录 message count 和 tool result
  count，方便 live run 进程可视化与排障。
- 为避免 provider adapter 或异常模型重复吐同一 tool_use，单个 provider conversation
  内已经见过的 `tool_call_id` 不会重复执行；这修复了 fake provider 不理解
  `provider_messages` 时自激循环到工具上限的问题。
- continuation 有 host-owned 上限：`_MAX_PROVIDER_TOOL_RESULT_CONTINUATIONS = 16`。
  超限后不继续递归，已产生的工具结果进入 journal/context，由外层 deep loop 重规划。

边界：这是运行时消息闭合，不是金融题规则。工具结果是 bounded projection，完整输出仍在
Holo journal/artifact；模型仍然负责解释工具结果、决定下一步、绑定公式和最终回答。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_processor_streaming.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase1_journal_store.py tests/test_kernel_v3_phase3_context_compiler.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_processor_streaming.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_phase5_semantic_processors.py tests/test_kernel_v3_processor_usage.py tests/test_kernel_v3_phase61_workloop.py -q
```

结果：

- `31 passed in 3.32s`
- `351 passed in 11.63s`
- `499 passed in 32.99s`

至此，单 agent loop 的 P0 substrate 已经具备：streaming tool executor、tool-use context、
tool discovery、context updates、context-aware tool expansion、tool-result provider
multi-round continuation、budget guard、agent trace 和 artifact/result replacement。下一步
必须进入 FB/FQA debug50 题型簇 live 验证，用真实线上做题结果来驱动剩余修复。

## 17. Tool input tolerance and SEC structured fact ranking checkpoint

用户继续强调：优先照搬成熟 agent loop 的成熟实现，不要自己造零散补丁。对照
TypeScript loop 后，本轮继续补的是工具执行合同，而不是单题答案规则：

- 成熟 loop 不假设模型每次都能生成完整强类型对象；host 应该在 schema 边界给出
  可恢复错误或做安全的最小规范化。
- 工具执行失败必须回流为模型可理解的 tool result，而不是因为少了一个非关键字段
  让整个 finance verifier 链断掉。
- facts/evidence/formula trace 这种中间对象要支持 model one-shot 传入的最小
  结构化 payload；完整 provenance 仍由 host/journal 维护。

真实 live trace 暴露了两个通用问题：

- `finance.verify_numeric` 被模型调用时，`facts` 里只有 metric/value 等最小字段；
  旧入口直接按 `FinanceFact.from_dict` 严格反序列化，因缺少 `ticker` 等字段失败。
  这导致 verifier tool observation 失败，后续只能靠内部 verifier/judge 修补。
- `financebench_id_00499` 的 capital intensity trace 中，ledger 同时存在正确的
  SEC XBRL `PropertyPlantAndEquipmentNet = 9.178B` 和一个 natural text 片段
  `property plant and equipment net = 1321`。旧排序只看 `metadata.source`，
  而 XBRL 事实没有写入 `source=structured`，于是 natural text 小片段错误胜出。

本轮修复：

- `finance.verify_numeric` 的 tool schema 明确接受 `FinanceFact` 完整行或模型
  one-shot 最小 fact 对象；formula trace、citation、evidence 也支持最小对象。
- `calculator.py` 在严格 `from_dict` 失败后，只对受支持的 finance contract 做
  安全规范化：填入稳定 synthetic id、source/evidence/citation fallback、metadata
  摘要和 payload hash。非 object 列表项仍被 schema/registry 拒绝。
- `formula_planner.py` 的事实排序现在能从 SEC concept/form/fp/source_uri 推断
  structured SEC XBRL 事实，即使 `metadata.source` 为空也不再排在 natural_text 后。
  `html_table_fact` 排在 natural_text 前，但不会伪装成 SEC XBRL concept。
- capital intensity PP&E/assets 绑定因此优先选择 `PropertyPlantAndEquipmentNet`
  的 SEC XBRL 值；host 只修事实来源优先级和 slot candidate binding，不判断
  “是否资本密集”这个语义结论。

结构验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py::test_finance_numeric_verifier_accepts_minimal_model_fact_evidence_rows tests/test_kernel_v3_finance_engine.py::test_capital_intensity_prefers_sec_xbrl_ppe_over_natural_text_fragment tests/test_kernel_v3_finance_engine.py::test_capital_intensity_model_outputs_support_verifier_answer_numbers tests/test_kernel_v3_finance_engine.py::test_finance_formula_planner_does_not_fill_capital_intensity_with_wrong_year_or_cost_of_revenue -q
.venv/bin/python -m py_compile kernel_v3/finance/calculator.py kernel_v3/finance/formula_planner.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_provider_native_tools.py tests/test_kernel_v3_processor_streaming.py tests/test_kernel_v3_finance_engine.py -q
git diff --check
```

结果：

- `4 passed in 1.49s`
- `py_compile` passed
- `353 passed in 11.66s`
- `git diff --check` clean

live 复测状态：

```text
.state/kernel_v3/bench/finance/run_fb_debug_o002_l001_live_20260618_streaming_v4.jsonl
.state/kernel_v3/bench/finance/run_fb_debug_o002_l001_live_20260618_streaming_v4.summary.json
```

这次不能作为能力证据：processor 调用没有真正发生，`tokens=0`，
`proc_errors=missing_api_key_env:7`。同时 UbuntuHolo 当前无法通过 Windows
interop 读取环境变量，`powershell.exe` 和 `cmd.exe` 都直接返回
`UtilBindVsockAnyPort: socket failed 1`。因此本轮只记录结构修复和无效 live
阻塞原因；下一次有效 finance live 必须先把 provider key 持久同步到 UbuntuHolo
环境，再重跑该题和 debug50 类型簇。

## 18. Live benchmark provider preflight checkpoint

上一节的无效 live rerun 暴露出另一个 P0 稳定性问题：当
`HOLO_V3_LIVE_MODEL=1` 但 provider key 对 UbuntuHolo 不可见时，旧 CLI 会放行
`bench finance`，然后每个 processor request 才返回 `missing_api_key_env`。这会
生成 `tokens=0` 的 benchmark row，容易被误读为金融做题失败或进入统计污染。

本轮补齐 live benchmark 启动前的 provider preflight：

- `bench finance` / chat / agent 的 live 入口会先检查 `DEEPSEEK_API_KEY`。
- 如果当前进程没有 key，会尝试从 Windows User/Machine environment 安全读取一次；
  成功时只注入当前 Python 进程环境，不打印、不写 journal。
- 如果 Windows interop 失败或没有 key，并且 `HOLO_V3_LIVE_MODEL=1`，入口直接返回
  `status=blocked, reason=missing_live_model_api_key`，包含 env 名和 sanitized
  diagnostics，但不创建 benchmark results/summary。
- 如果既没有 key 也没有 live gate，仍保持旧的 `live_model_not_enabled` 语义。
- `--predictions` 离线评分路径不受影响；它仍可在无 provider key 时运行。

结构和 CLI 验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_phase62_chat_runtime.py::test_phase62_live_gate_blocks_when_enabled_but_api_key_missing tests/test_kernel_v3_phase62_chat_runtime.py::test_phase62_live_gate_imports_windows_api_key_without_exposing_value tests/test_kernel_v3_phase62_chat_runtime.py::test_phase62_cli_chat_online_mode_uses_model_backed_processors tests/test_kernel_v3_phase62_chat_runtime.py::test_phase62_successful_semantic_response_is_not_converted_to_generic_pending_input -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py::test_finance_benchmark_live_blocks_before_writing_rows_when_api_key_missing tests/test_kernel_v3_finance_benchmark.py::test_finance_benchmark_cli_scores_prediction_file -q
.venv/bin/python -m pytest tests/test_kernel_v3_phase62_chat_runtime.py tests/test_kernel_v3_finance_benchmark.py -q
.venv/bin/python -m py_compile kernel_v3/cli.py tests/test_kernel_v3_phase62_chat_runtime.py tests/test_kernel_v3_finance_benchmark.py
```

结果：

- `4 passed in 1.92s`
- `2 passed in 26.86s`
- `107 passed in 192.10s`
- `py_compile` passed

实际 CLI smoke：

```text
HOLO_V3_LIVE_MODEL=1 env -u DEEPSEEK_API_KEY .venv/bin/python -m kernel_v3.cli ... bench finance ...
```

结果为 `status=blocked, reason=missing_live_model_api_key`，退出码 `1`，且临时
`results.jsonl` / `summary.json` 均未创建。当前 Windows interop diagnostic 仍是
`UtilBindVsockAnyPort: socket failed 1`，所以真正恢复 live 刷分前仍需把 provider
key 直接放进 UbuntuHolo 环境。

## 19. No-gold debug50 requirements audit checkpoint

用户要求停止逐题补丁，先检查系统合同，按类型簇突破 debug50。为此本轮新增
`bench finance-requirements-audit`：

```bash
.venv/bin/python -m kernel_v3.cli bench finance-requirements-audit \
  --dataset data/bench/finance/financebench_doc_retrieval.jsonl \
  --split debug50 \
  --format text
```

该入口只看题面和公开元数据，不读取或输出 `gold_answer`、`numeric_value`、
`tolerance`、`evidence_excerpt`、reference evidence 或 dev gold。它输出
`holo.kernel_v3.finance_requirements_audit.v1`，并固定标记
`no_gold_fields_used=true`、`capability_claim=false`、
`benchmark_progress_claim=false`。

实跑 debug50 结构审查结果：

- `items=50`
- `contract_covered=50/50`
- `direct_line_item_or_disclosure=42`
- `defined_formula_calculation=33`
- `calculation_then_business_judgment=30`
- `driver_attribution_or_bridge=19`
- `table_ranking_or_comparison=7`
- `multi_entity_compare=9`

这一步对应成熟 agent loop 的上层能力：先把任务转成 TaskSpec /
EvidenceSpec / TransformSpec / tool workbench 的需求图，再让 LLM one-shot
选择和调用工具。它不替模型做答案规则，不做 table cheating，也不是
FinanceBench/FQA 分数。后续 live debug 应按这些任务族推进，而不是围绕单题
重复打补丁。

## 20. Finance question requirements ABI checkpoint

上一节的 `finance-requirements-audit` 仍偏向人读报告；按成熟 agent loop 的要求，
任务需求必须进入模型下一轮上下文和 provider 发包路径。本轮把 no-gold 题面需求
推断抽成通用模块：

- 新增 `kernel_v3/finance/requirements.py`。
- `bench finance-requirements-audit` 与 runtime 共享同一个
  `infer_finance_question_requirements(...)`。
- finance-capability 的 `_planner_directive(...)` 现在包含
  `finance_question_requirements`，schema 为
  `holo.kernel_v3.finance_question_requirements.v1`。
- `_compact_agent_runtime_directive_for_prompt(...)` 和 provider compact
  `_compact_runtime_directive_for_provider(...)` 都保留该摘要。
- `finance_working_state.workbench` 也读取同一 requirements 摘要，把
  question families、required tool categories 和 required loop stages 暴露给
  后续 planner turn。
- 原来 directive 里过于具体的 inventory/DIO 提示已替换成通用
  formula/comparison slot-bind/transform 指令，避免回到单题补丁。
- `kernel_v3/processors/contracts.py` 中同类 DIO 专题提示也已改成
  formula / efficiency / ratio / ranking / comparison 的通用 slot/workbench
  合同。

该 ABI 仍明确标记 `gold_or_reference_values_used=false`，只从题面和公开元数据
推断任务族、risk flags、工具类别和 loop 阶段。它不决定答案、不选择 filing line
item、不设置硬阈值；模型仍负责工具选择、事实绑定、公式选择和金融语义判断。

结构验证：

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_engine.py::test_finance_capability_planner_exposes_question_requirements_without_task_patch \
  tests/test_kernel_v3_finance_engine.py::test_finance_capability_planner_directive_preserves_full_open_tool_surface \
  tests/test_kernel_v3_finance_engine.py::test_finance_capability_provider_compact_preserves_one_shot_tool_surface \
  tests/test_kernel_v3_finance_benchmark.py::test_finance_requirements_audit_excludes_gold_reference_values \
  tests/test_kernel_v3_finance_benchmark.py::test_finance_requirements_audit_cli_is_no_gold_structural_check \
  tests/test_kernel_v3_finance_benchmark.py::test_finance_requirements_audit_text_renderer_marks_scope -q
```

结果：`6 passed in 1.85s`。

后续因 processor contract 也同步泛化，补跑：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
```

结果：`303 passed in 8.42s`。

再次运行 debug50 no-gold audit，结果保持：

- `items=50`
- `contract_covered=50/50`
- `direct_line_item_or_disclosure=42`
- `defined_formula_calculation=33`
- `calculation_then_business_judgment=30`
- `driver_attribution_or_bridge=19`
- `table_ranking_or_comparison=7`
- `multi_entity_compare=9`

说明：这仍不是 live benchmark accuracy；它只是把“按类型簇突破”的任务需求
从 CLI 报告推进到模型真实可见的 agent-loop ABI。

## 21. Type-cluster benchmark slicing checkpoint

为了真正开始“按类型簇刷 debug50”，本轮把 requirements ABI 接入
`bench finance` 运行入口。现在可以用题面需求切片选择 live/prediction scoring
子集：

```bash
.venv/bin/python -m kernel_v3.cli bench finance \
  --dataset data/bench/finance/financebench_doc_retrieval.jsonl \
  --split debug50 \
  --requirements-family table_ranking_or_comparison \
  --requirements-limit 3
```

支持的 no-gold 过滤维度：

- `--requirements-family`
- `--requirements-tool-category`
- `--requirements-risk-flag`
- `--requirements-loop-stage`
- `--requirements-offset`
- `--requirements-limit`

过滤只读取题面和公开元数据；输出结果 metadata 会写入
`requirements_filter`，包含 `no_gold_fields_used=true`、selected item ids、
matched/selected counts 和 filter 条件。空 slice 会返回
`empty_finance_requirements_slice`，避免误把空 summary 当成结果。

实跑 smoke：

```bash
.venv/bin/python -m kernel_v3.cli bench finance-requirements-audit \
  --dataset data/bench/finance/financebench_doc_retrieval.jsonl \
  --split debug50 \
  --requirements-family table_ranking_or_comparison \
  --requirements-limit 3 \
  --format text
```

结果列出 3 个表格排序/比较类型簇题：

- `financebench_id_01865`
- `financebench_id_01858`
- `financebench_id_08286`

结构测试：

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_benchmark.py::test_finance_requirements_filter_selects_type_cluster_without_gold_values \
  tests/test_kernel_v3_finance_benchmark.py::test_finance_benchmark_cli_scores_prediction_file_with_requirements_family_slice \
  tests/test_kernel_v3_finance_benchmark.py::test_finance_requirements_audit_excludes_gold_reference_values \
  tests/test_kernel_v3_finance_benchmark.py::test_finance_requirements_audit_cli_is_no_gold_structural_check -q
```

结果：`4 passed in 26.88s`。

完整 finance benchmark 结构测试随后通过：`60 passed in 172.52s`。

说明：这一步仍不是 live accuracy。它把后续 live debug 的单位从 offset 单题推进到
type-cluster slice，下一步可以按公式题、表格题、driver/bridge 题分别跑小批 live。

## 22. Requirement-aware native tool loading checkpoint

上一节完成了 type-cluster slicing，但 mature agent loop 还要求“任务需求”影响
实际 provider/native tool surface，而不是只放在 prompt 文本里。本轮把
`finance_question_requirements.required_tool_categories` 和 `risk_flags` 接入
`DeepAgentLoopController` 的 context-requested tool expansion：

- `structured_sec_facts` -> `sec.edgar.financials`
- `document_table_extraction` -> `document.docling.convert` /
  `document.trafilatura.extract`
- `table_operations` -> `data.table.query`
- `arithmetic` -> `calculator.compute`
- `numeric_verification` -> `finance.verify_numeric`
- `source_acquisition` / primary filing risk -> `retrieval.run` /
  `sec.edgar.company_filings`
- temporary workbench / table-sort / bridge risk -> `data.table.query` /
  `script.exec`

这只影响 deferred/native tool 的展开优先级，不自动执行工具、不选择事实、不决定答案。
模型仍负责 one-shot 工具调用，host 仍负责 policy/schema/execution/journal/verifier。

结构验证：

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_deep_agent_loop.py::test_assistant_turn_prompt_expands_finance_requirement_category_tools \
  tests/test_kernel_v3_deep_agent_loop.py::test_streaming_planner_expands_finance_requirement_category_native_tools \
  tests/test_kernel_v3_deep_agent_loop.py::test_streaming_planner_expands_context_requested_deferred_native_tool \
  tests/test_kernel_v3_provider_native_tools.py::test_native_tool_surface_expands_context_requested_deferred_tool_before_ordinary_tools -q
```

结果：`4 passed in 0.52s`。

完整相关结构测试：

- `tests/test_kernel_v3_deep_agent_loop.py`: `33 passed in 3.38s`
- `tests/test_kernel_v3_provider_native_tools.py`: `5 passed in 0.19s`

说明：这仍不是 FinanceBench/FQA accuracy，但它补齐了一个 P0 运行链路：
题面 requirements -> context requested tools -> prompt tool surface ->
provider-native tools。后续 live slice 不需要模型先绕一轮 `tool.discovery` 才看到
表格/SEC/calculator/verifier工具 schema。

## 23. ToolSearch-style discovery continuation checkpoint

用户再次强调：优先照搬成熟 agent loop 的实现，不要继续在旧 harness 上小修小补。
本轮对照本地 TypeScript 项目的 `ToolSearchTool`、`queryLoop`、
`StreamingToolExecutor` 后，补的是 ToolSearch 语义本身：

- `tool.discovery` 支持 `query="select:tool.a,tool.b"` 精确加载，返回
  `matched_tool_names` / `missing_tool_names` / `requested_tool_names`。
- discovery 返回的 manifest summary 被压缩，只保留模型下一步调用所需的
  name、description、input_schema 和关键 runtime 字段，避免 discovery 结果挤爆
  `recent_observations`。
- provider streaming continuation 每一轮都会重新构建 native tool surface。
  如果上一轮 `tool.discovery` 发现了 allowed deferred tool，下一轮 continuation
  会把该工具 schema 暴露给 provider-native tool call。
- non-streaming JSON-turn 也走同一链路：`tool.discovery` observation 会派生
  `tool_context_update`，把 matched tools 写入 `requested_tool_names` /
  `loaded_tool_names`；下一轮 `_assistant_turn_prompt(...)` 因此能把 deferred
  tool 从 `deferred_tools` 提升到 `visible_tools`。
- 这不扩大权限边界：allowed-tool set、policy gate、schema validation、journal
  和 verifier 仍由 host 控制；模型只获得“可调用工作台”的正确入口。

同时补了 live-slice preflight 可观测性：

- `bench finance` 在带 requirements filter 且没有 `--predictions` 时，会先执行
  no-gold requirements slice，再做 live-model/provider preflight。
- 如果 API key 或 live model 开关阻断，payload 仍包含 `requirements_filter`、
  `selected_item_ids`、工具类别摘要和 `preflight_item_count`。
- 该路径不写 results/summary，不启动 fake run，不读 gold/reference，不报告
  benchmark accuracy。

本轮结构验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_tool_use.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_provider_native_tools.py -q
```

结果：

- `11 passed in 0.34s`
- `35 passed in 3.39s`
- `61 passed in 181.40s`
- `5 passed in 0.22s`

实际 CLI preflight smoke：

```bash
.venv/bin/python -m kernel_v3.cli \
  --journal /tmp/holo_live_preflight.journal.jsonl \
  --index /tmp/holo_live_preflight.sqlite \
  bench finance \
  --dataset data/bench/finance/financebench_doc_retrieval.jsonl \
  --split debug50 \
  --requirements-family table_ranking_or_comparison \
  --requirements-limit 1 \
  --output /tmp/holo_live_preflight.results.jsonl \
  --summary-output /tmp/holo_live_preflight.summary.json
```

返回 `status=blocked` / `reason=live_model_not_enabled`，但保留
`selected_item_ids=["financebench_id_01865"]`，并确认 results/summary 未写出。
这说明切片和工具需求链路可观测，但不构成 live finance score。

## 24. Provider continuation parse-error boundary

继续对照成熟 TypeScript loop 的工具协议不变量后，本轮收紧 provider
continuation：只有真实已执行工具结果才会被构造成 provider-compatible
assistant/tool messages 回灌给同一个 provider conversation。

此前风险：

- streamed malformed tool arguments、`stream_error` 或 `stream_end(status!=ok)`
  会产生 `tool_call_parse_error` observation；
- 这些 parse error item 也可能进入 provider continuation；
- 对于并非真实 provider tool_call 的错误，host 会构造 synthetic
  `__invalid_tool_call__` assistant tool_call，这违反“每个 tool_result 对应真实
  tool_use”的成熟 loop 语义。

现在：

- `tool_call_parse_error` / `__invalid_tool_call__` 仍写入 journal、
  `tool_batch_result` 和后续 context，供外层 loop 重规划；
- 它们不再生成 provider conversation 内的 synthetic assistant/tool messages；
- 真实执行成功/失败/blocked 的工具结果仍正常通过
  `provider_tool_result_continuation` 回灌。

结构验证：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
```

结果：`36 passed in 3.42s`。

这一步修的是 provider/tool 协议完整性，不是 FinanceBench/FQA accuracy。

## 25. Provider-visible full tool-result artifact checkpoint

用户再次强调：优先照搬成熟 agent loop 的成熟实现，不要在旧 loop 上零散自研。
本轮继续对照本地 TypeScript 项目的 `StreamingToolExecutor`、`toolExecution` 和
tool-result storage 思想，补齐一个通用合同：工具结果进入 provider continuation
时，模型必须拿到可读回完整结果的稳定句柄，而不是只能看到短 projection。

此前 Holo 已有 `tool_result_full` artifact 和 batch-level replacement，但
streaming provider continuation 发生在 `_tool_batch_observation` 写 full artifact
之前。因此同一 provider conversation 里回灌的 tool message 只能看到工具自身
artifact refs，不一定包含完整 tool-result JSON 的 artifact id。这会影响所有长结果
任务：SEC filing、PDF/table extraction、网页正文、计算日志、检索报告都可能需要
模型先看 bounded projection，再自主决定是否 `artifact.read` 完整结果。

本轮补齐：

- `_ToolExecutionItem` 新增 `tool_result_artifact_ref`，工具执行完成时立即写入
  stable `tool_result_full` artifact，而不是等 batch observation 才写。
- provider continuation 的 tool-result payload 现在包含
  `tool_result_artifact_id` 和 `artifact_read_hint`，明确提示模型可以用
  `artifact.read` 读取完整工具结果 JSON。
- batch observation 复用同一个 artifact ref，不重复写 full payload；replacement
  的 `artifact_refs` 仍指向同一 artifact。
- journal observation 的 artifact refs 和 `tool_context_update` 做预算边界：
  小结果不把 full artifact hint 投入下一轮 context，避免上下文膨胀；只有 projection
  被截断的长结果才进入外层 context 的 artifact-read hint。
- artifact hint 在 context update 的 8 条上限中保留优先级，防止长结果读回路径被
  其他低价值 update 挤掉。

结构验证：

```bash
.venv/bin/python -m py_compile kernel_v3/deep_loop.py
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_provider_native_tools.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
```

结果：

- `deep_agent_loop`: `36 passed in 3.47s`
- `tool_use + provider_native_tools`: `16 passed in 0.49s`
- `finance_benchmark`: `61 passed in 177.12s`

新增覆盖：

- provider continuation 中的 tool message 含有 `tool_result_artifact_id`、
  `artifact_read_hint.tool == "artifact.read"`，且 artifact store 能读回
  `holo.kernel_v3.tool_result_full.v1` payload。
- 长结果 batch replacement 仍持久化完整 artifact，并通过 `tool_context_update`
  暴露 artifact-read hint。

说明：这是通用 agent loop/tool-result contract 成熟度修复，不是
FinanceBench/FinQA accuracy。当前 UbuntuHolo 环境里 live key/model 变量仍未暴露，
因此本轮没有新增 live 金融分数。

## 26. Artifact workbench query checkpoint

上一节让 provider continuation 能看到 full tool-result artifact，但如果模型只能
继续整包 `artifact.read`，长 SEC filing、Docling 表格、检索报告和工具结果仍会造成
上下文膨胀和重复读取。本轮继续按成熟 agent loop 的工作台思想补齐：
artifact 不是只能读全文，而应支持模型 one-shot 做有界结构查询。

本轮新增：

- `artifact.query` 工具，由 `register_artifact_tools(...)` 注册，默认 always-load、
  read-only、concurrency-safe。
- 支持 JSON path 查询，例如 `observation.content.records`、
  `$.facts.Revenue`、`records[0]` 和 `*` wildcard。
- 支持对 JSON subtree 做关键词搜索；当 path 指向 list[dict] 时，返回匹配行，
  适合 SEC/table/document rows 的候选筛选。
- 支持非 JSON artifact 的 bounded text-line search。
- 输出只包含 bounded matches、shape、preview 和 compact value；不做财务语义判断、
  不选择 line item、不计算公式、不读取 gold/reference。
- provider continuation 和 tool context 的 full-result hint 现在同时包含
  `artifact_query_hint`；replacement read hint 也改为优先 `artifact.query`，必要时
  再 `artifact.read`。
- finance loop 的标准工具接口和 capability catalog 已加入 `artifact.query`，让模型
  知道长 artifact 应先窄查，再决定是否整包读取。

结构验证：

```bash
.venv/bin/python -m py_compile \
  kernel_v3/tool_use.py kernel_v3/deep_loop.py kernel_v3/tool_result_budget.py \
  kernel_v3/capabilities.py kernel_v3/agent/runtime.py \
  tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_deep_agent_loop.py
.venv/bin/python -m pytest \
  tests/test_kernel_v3_tool_use.py \
  tests/test_kernel_v3_deep_agent_loop.py \
  tests/test_kernel_v3_provider_native_tools.py \
  tests/test_kernel_v3_finance_open_components.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_processor_usage.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
```

结果：

- `tool_use + deep_loop + provider_native + finance_open_components`: `81 passed in 5.96s`
- `processor_usage`: `11 passed in 0.67s`
- `finance_benchmark`: `61 passed in 170.80s`

新增覆盖：

- JSON artifact 可按 path 查询并按关键词返回匹配 table row。
- JSON artifact 可无 query 返回目标 path 的 shape/value preview。
- 文本 artifact 可按多词 line search 返回 bounded lines。
- provider continuation 的 full tool-result payload 包含 `artifact_query_hint`。
- 长结果 replacement 的 hint 包含 `artifact.query` 和 `artifact.read`。

说明：这是 P0 mature-loop 工作台能力，不是 FinanceBench/FinQA accuracy。它减少
未来 live debug 中反复整包 `artifact.read` 的概率，并给模型一个更接近成熟 agent
loop 的临时工作台查询接口。

## 27. Artifact query exposure checkpoint

复查后发现上一节只证明了 `artifact.query` 工具本身可用，但还没有完全证明真实
AgentRuntime / planner allowed surface 会把它暴露给模型。成熟 agent loop 的要求不是
“工具注册在 registry 里”，而是模型 one-shot 时能看到可调用 schema，并且
`tool.discovery` 也认为它是 allowed tool。

本轮补齐：

- `AgentRuntime._with_foundational_tools(...)` 的 `tool.discovery` allowed set 加入
  `artifact.query`。
- `_planner_allowed_tool_names(...)` 默认把 `artifact.query` 和 `artifact.read` 一起
  加入 model planner / deep planner 可用工具集合。
- `task_recipe("retrieval_answer")`、`workspace_answer`、`workspace_write` 默认
  allowed_tools 均加入 `artifact.query`。
- finance open-component / research profile runtime registry 测试确认
  `artifact.query` 进入 recipe allowed tools 和 runtime manifests。
- finance fast planner 测试确认 `_planner_allowed_tool_names(recipe)` 包含
  `artifact.query`，模型 planner 可在同一 allowed set 中选择 verifier、calculator、
  retrieval 和 artifact query。

结构验证：

```bash
.venv/bin/python -m py_compile \
  kernel_v3/agent/runtime.py \
  tests/test_kernel_v3_finance_open_components.py \
  tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest \
  tests/test_kernel_v3_tool_use.py \
  tests/test_kernel_v3_deep_agent_loop.py \
  tests/test_kernel_v3_provider_native_tools.py \
  tests/test_kernel_v3_finance_open_components.py \
  tests/test_kernel_v3_processor_usage.py -q
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_engine.py::test_finance_fast_recipe_exposes_composable_toolchain_tools \
  tests/test_kernel_v3_finance_engine.py::test_finance_fast_model_planner_can_select_verify_numeric_tool \
  tests/test_kernel_v3_finance_engine.py::test_finance_capability_planner_directive_shows_script_toolchain -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
```

结果：

- `tool/deep/provider/finance-open/processor`: `92 passed in 6.32s`
- `finance_engine targeted`: `3 passed in 0.67s`
- `finance_benchmark`: `61 passed in 176.06s`

说明：这是工具暴露链路修复，不是 live finance score。当前 UbuntuHolo 仍未暴露
`DEEPSEEK_API_KEY` / `HOLO_V3_LIVE_MODEL`，因此本轮仍不能报告新的
FinanceBench/FinQA 准确率。

## 28. Running sibling abort checkpoint

继续按“优先照搬成熟 agent loop”的方向，本轮补上外部 TypeScript
`StreamingToolExecutor` 的 running sibling abort 语义。此前 Holo 只能把失败后尚未
启动的 pending 工具标成 cancelled；已经运行中的并发兄弟工具只能靠自己的 timeout
结束。这会在 live 金融检索、文档解析和脚本工具里放大资源占用风险。

本轮补齐：

- `ToolRuntimeSpec` 新增 `failure_cancels_siblings`。普通 read/network 失败默认
  不取消兄弟工具；write/shell/destructive 或非读非并发安全失败默认取消；协调类
  工具可显式声明失败后取消兄弟工具。
- `StreamingToolExecutor` 新增 `abort_one` 回调，在 `_outcome_cancels_siblings`
  首次成立时向所有 running sibling 发送 cooperative abort，同时保留 pending
  sibling 的 `cancel_one` 行为。
- `DeepAgentLoopController` 把 `abort_one` 接到每个 prepared tool 的
  `ToolAbortSignal`，并写入 `abort_requested` tool execution event，reason 为
  `sibling_tool_failed`。
- 工具侧继续通过 `_host_context` 和 `tool_abort_requested(...)` 感知中止请求；
  agent loop 合同已经闭合，后续剩余工作是把 shell/script/network/document 工具
  具体接到进程组、HTTP request 或 worker process cancellation。

结构验证：

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_tool_use.py::test_streaming_tool_executor_abort_callback_reaches_running_siblings \
  tests/test_kernel_v3_deep_agent_loop.py::test_deep_loop_runtime_failure_requests_abort_for_running_sibling_tool -q
.venv/bin/python -m py_compile kernel_v3/tool_use.py kernel_v3/deep_loop.py kernel_v3/tool_runtime.py
.venv/bin/python -m pytest \
  tests/test_kernel_v3_tool_use.py \
  tests/test_kernel_v3_deep_agent_loop.py \
  tests/test_kernel_v3_provider_native_tools.py \
  tests/test_kernel_v3_finance_open_components.py \
  tests/test_kernel_v3_processor_usage.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
```

结果：

- `2 passed in 0.57s`
- `py_compile` passed
- `tool/deep/provider/finance-open/processor`: `94 passed in 6.26s`
- `finance_benchmark` harness structural tests: `61 passed in 173.79s`

说明：这是 agent-loop 稳定性和资源边界修复，不是 FinanceBench/FinQA accuracy。

## 29. Deep batch host-guard terminal boundary

本轮继续按“优先照搬成熟 agent loop，而不是继续单题补丁”的方向推进。上一轮 live
诊断在 `financebench_id_04672` 上证明 provider/key/streaming 工具链已经能跑起来，
但也暴露了一个更通用的 loop 缺陷：deep batch 内部已经出现
`host_guard reason=max_tool_calls`，外层 deep loop 仍把整个
`tool_batch_result status=partial` 当普通 observation，先调用 evaluator，再允许后续
turn 继续膨胀上下文。这不是金融题规则问题，而是成熟 agent loop 的 hard host
boundary 没有完全闭合。

本轮按外部 TypeScript `query` / `StreamingToolExecutor` 的思想补齐：

- 模型只负责语义决策和工具选择；host 负责预算、权限、执行、abort、stop 和记录。
- `DeepAgentLoopController` 现在会在调用 evaluator 之前检查
  `tool_batch_result.content.results[]`。
- 若任一子结果是 `status=blocked` 且来自 `loop_guard` / `host_guard`，并携带
  `max_tool_calls` 或 `max_network_fetches`，deep loop 立即写出
  `step_limit_exceeded` feedback 和 `guard` 记录。
- 普通 evaluator 不再收到这个 oversized post-budget context；只有 evaluator 显式实现
  `finalize_guard` 时，host 才给它一次 guard-finalize 机会，用已有证据收尾。
- 这不是 FinanceBench 打表：host 不选择财务事实、公式、引用或答案，只是在工具预算
  已被 host 阻断时停止无效继续。

结构验证：

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_deep_agent_loop.py::test_deep_agent_loop_stops_before_evaluator_when_batch_contains_host_guard -q
.venv/bin/python -m py_compile \
  kernel_v3/deep_loop.py \
  tests/test_kernel_v3_deep_agent_loop.py
.venv/bin/python -m pytest \
  tests/test_kernel_v3_deep_agent_loop.py \
  tests/test_kernel_v3_tool_use.py -q
.venv/bin/python -m pytest \
  tests/test_kernel_v3_phase61_workloop.py \
  tests/test_kernel_v3_phase3_context_compiler.py -q
.venv/bin/python -m pytest \
  tests/test_kernel_v3_deep_agent_loop.py \
  tests/test_kernel_v3_tool_use.py \
  tests/test_kernel_v3_provider_native_tools.py \
  tests/test_kernel_v3_processor_streaming.py \
  tests/test_kernel_v3_finance_open_components.py \
  tests/test_kernel_v3_finance_tool_readiness.py \
  tests/test_kernel_v3_phase61_workloop.py -q
git diff --check
```

结果：

- targeted batch host-guard test: `1 passed in 0.52s`
- `py_compile` passed
- `deep-loop/tool-use`: `53 passed in 3.84s`
- `workloop/context-compiler`: `42 passed in 9.39s`
- core loop/tool/provider/finance-open structural set: `125 passed in 17.28s`
- `git diff --check` passed

说明：这是 live diagnostic 驱动的 agent-loop 稳定性修复，不是新的
FinanceBench/FinQA score。下一步做 live debug50 类型簇时，这个边界应防止工具预算
耗尽后继续向模型发送 20-30 万字符级上下文。

## 30. Mature-loop exception/result recovery checkpoint

用户再次明确：优先照搬成熟 agent loop 的实现思想，不再自造低层循环。本轮继续
对照本地 TypeScript 项目的 `QueryEngine`、`query.ts`、
`StreamingToolExecutor`、`toolExecution.ts`、`Tool.ts` 和 `ToolSearchTool`。
这次迁移的重点不是 UI、命令系统或多 agent，而是单 agent 工具闭环：

- 模型发出 tool use；
- host 做 schema、权限、预算、并发、超时、执行、记录；
- 每个 tool use 都必须得到 tool result，包括失败、取消、host 异常；
- tool result 以 bounded provider continuation 和 durable journal/artifact 形式回到下一轮；
- schema 不清时通过 tool discovery 恢复，而不是让模型盲猜参数。

本轮补齐：

- live 模型预检支持从显式 `DEEPSEEK_API_KEY_FILE`、
  `HOLO_DEEPSEEK_API_KEY_FILE` 或默认 `.holo_runtime/secrets/deepseek.key`
  导入 key；诊断只暴露来源，不打印密钥。
- `_live_processor_fabric(...)` 对 DeepSeek provider 也走同一 preflight，避免
  `model-smoke`/chat/agent/bench 路径各自失败。
- streaming provider continuation 在每轮工具结果后检查刚产生的
  `_ToolExecutionItem`；如果出现 `max_tool_calls` / `max_network_fetches`
  等 host budget guard，立即写
  `holo.kernel_v3.provider_tool_result_continuation_budget_guard.v1` 并停止继续
  调 provider。外层 deep loop 从 journaled batch 进入 host guard/finalize。
- `StreamingToolExecutor` 新增 `exception_one` 回调。执行线程里的 host 异常
  可以被转换成 outcome，而不是冒泡打断整个 loop。
- `DeepAgentLoopController` 把该回调绑定为 `tool_host_exception` observation，
  保留 `tool_call_id`、action、artifact 和 batch 结果；模型/evaluator 下一轮
  看到的是失败工具结果，不是进程崩溃。
- `ToolRegistry` 对 `invalid_tool_payload` 增加 model-visible 恢复协议：
  `schema_available_via=tool.discovery`，并提示
  `tool.discovery query='select:<tool>'` 后按返回 `input_schema` 重试。

结构验证：

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_tool_use.py::test_invalid_tool_payload_points_model_to_tool_discovery_recovery \
  tests/test_kernel_v3_tool_use.py::test_streaming_tool_executor_converts_host_exception_to_outcome -q
.venv/bin/python -m pytest \
  tests/test_kernel_v3_deep_agent_loop.py::test_deep_agent_loop_records_host_tool_exception_as_tool_result \
  tests/test_kernel_v3_deep_agent_loop.py::test_streaming_provider_continuation_stops_when_round_hits_tool_budget_guard -q
.venv/bin/python -m py_compile \
  kernel_v3/tool_use.py kernel_v3/deep_loop.py kernel_v3/tools.py \
  tests/test_kernel_v3_tool_use.py tests/test_kernel_v3_deep_agent_loop.py
.venv/bin/python -m pytest \
  tests/test_kernel_v3_tool_use.py \
  tests/test_kernel_v3_deep_agent_loop.py \
  tests/test_kernel_v3_provider_native_tools.py -q
```

结果：

- targeted tool-use tests: `2 passed in 0.13s`
- targeted deep-loop tests: `2 passed in 0.57s`
- `py_compile` passed
- broader tool/deep/provider-native set: `62 passed in 3.99s`
- final core loop/tool/provider/processor/finance-open/workloop set:
  `129 passed in 18.77s`
- final finance benchmark harness structural tests: `61 passed in 175.32s`
- `git diff --check` passed

同一 checkpoint 线还保留上一轮结构验证结果：

- core loop/tool/provider/finance-open set: `126 passed in 18.97s`
- finance benchmark harness structural tests: `61 passed in 169.30s`

Live 诊断：

- DeepSeek `model-smoke` 通过本地 key-file preflight 成功返回结构化
  `planner.propose`，文本为 `model smoke ok`。这是 provider/key 连通性证据，
  不是金融分数。
- `financebench_id_04672` live probe 在 streaming continuation guard 后完整结束，
  不再需要手动 interrupt；但结果为 `numeric_outside_tolerance`，`0/1`，
  matched values 包含 `1.577`，dev-gold post-run expected numeric 为 `8.7`。
  该 run 证明 provider/SEC/tool loop 可以结束并被评分，但金融答案仍失败。

结论：

- 可以声明：成熟 loop 的 key preflight、streaming budget stop、host exception
  result recovery、invalid payload discovery recovery 已落地并通过结构测试。
- 不可以声明：FinanceBench/FinQA 准确率提升。
- 下一步应继续从 `financebench_id_04672` 的 live journal 复盘 slot/statement
  binding：为什么缺 `balance_sheet net PP&E` 时 finalizer 仍用 cash-flow PP&E
  purchases 或错误数值完成。这是证据槽和合成 gate 的通用问题，不应写成 3M 规则。

## 31. Mature-loop lifecycle trace checkpoint

用户再次强调优先照搬成熟 agent loop 的实现，不要继续自研零散循环。本轮继续对照
本地 TypeScript 项目的 `QueryEngine.submitMessage(...)` / `queryLoop(...)`：
成熟 loop 在每次 query 结束时都会产生明确 result/transition 合同，包含
stop reason、permission denials、tool result、预算错误、执行错误等。Holo
此前虽然已经 journal 了 assistant turn、action、observation、feedback、guard
和最终 result，但“每一轮为什么继续/返回/guard”的结构仍需要从多条记录里人工推断。

本轮补齐：

- `DeepAgentLoopController` 每个 step 在继续或返回前写入
  `agent_loop_turn_result` ledger record。
- 该 record 统一记录：
  - `phase`: `terminal_turn` / `tool_turn`
  - `transition`: `continue` / `return` / `return_guard` /
    `return_continuation_guard`
  - `turn_id`、assistant tool-call 数、parse-error 数、final-answer 状态
  - feedback status / stop reason / answer 是否存在 / missing evidence
  - guard stop reason
  - tool-call / network-fetch / artifact-byte counters
  - tool result status/kind counts、failed tool summaries、observation refs
- `ContextPackCompiler` 把 compact 后的 `agent_loop_turn_result` 纳入
  `agent_trace`，并在预算不足时保留最小 lifecycle 摘要。
- 模型下一轮不再只能从分散的 action/observation/feedback 推断状态，而是能直接
  看到上一轮的 loop transition、失败工具和 guard 原因。

这不是金融规则，也不是 benchmark 答案表。它只把成熟 agent loop 的
per-turn lifecycle/result 合同迁移到 Holo 的 host-owned journal 和
model-visible trace 中。

结构验证：

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_deep_agent_loop.py \
  tests/test_kernel_v3_phase3_context_compiler.py::test_context_pack_exposes_agent_trace_for_model_tool_loop -q
.venv/bin/python -m py_compile \
  kernel_v3/deep_loop.py \
  kernel_v3/context/compiler.py \
  tests/test_kernel_v3_deep_agent_loop.py \
  tests/test_kernel_v3_phase3_context_compiler.py
.venv/bin/python -m pytest \
  tests/test_kernel_v3_tool_use.py \
  tests/test_kernel_v3_provider_native_tools.py \
  tests/test_kernel_v3_phase3_context_compiler.py \
  tests/test_kernel_v3_phase1_context_trace.py -q
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_engine.py \
  tests/test_kernel_v3_phase61_workloop.py -q
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_open_components.py \
  tests/test_kernel_v3_finance_tool_readiness.py \
  tests/test_kernel_v3_provider_native_tools.py \
  tests/test_kernel_v3_tool_use.py -q
```

结果：

- targeted deep-loop/context test: `41 passed in 3.56s`
- `py_compile` passed
- context/tool/provider set: `34 passed in 0.72s`
- finance engine/workloop set: `335 passed in 17.64s`
- finance-open/tool-readiness/provider/tool set: `52 passed in 4.69s`

说明：这是 mature-loop lifecycle/trace 合同修复，不是 FinanceBench / FinQA
准确率。下一步仍应回到 live debug50 类型簇，验证模型是否能利用
`agent_trace.agent_loop_turn_result` 更稳定地从缺槽、失败工具、budget guard 中
恢复。

## 32. Mature-loop finalization missing-slot gate checkpoint

用户继续强调优先照搬成熟 agent loop 的实现，不要把单题失败继续写成零散补丁。
本轮回到 `financebench_id_04672` 的 live 失败复盘：系统已经看到目标题缺
balance-sheet `property_plant_and_equipment_net`，但 finalization 仍允许合成答案
把 cash-flow `Purchases of PP&E` 这类邻近值当成核心数字进入 numeric verifier。
这不是 3M 规则问题，而是成熟 loop 的 terminal contract 缺口：final answer
必须证明 required answer slots 已满足，或明确把答案降级为不可得/未单列。

本轮补齐：

- `AgentRuntime._synthesize_retrieval_final(...)` 在 processor 产出
  `FinalAnswer` 后、质量检查和 numeric verifier 前新增
  `missing_required_finance_slots_v1` gate。
- gate 从 retrieval report diagnostics、retrieval workbench decision、
  model/host slot frame、`finance.slot_bind`、`TransformPlan` 和 numeric
  verification state 中收集 unresolved required finance slots。
- 已由后续状态解决的槽位会被扣减：例如 ready `TransformPlan` 中的
  `fiscal_days=365` 不再被早期 slot_frame 的缺槽快照误拦。
- optional formula planner 的缺槽不会阻断 source-grounded explanation；
  只有 report/workbench/model-owned required slot 或 slot_frame `required_slots`
  明确指向的 answer slot 才能触发终止 gate。
- 若初次合成在缺 required slot 时仍 headline proxy numeric answer，host 记录
  failed synthesis gate，并让 LLM 进行一次 repair：未单列时必须以
  `Not separately itemized;` 开头，证据不存在时必须以
  `Not available in the provided evidence;` 开头；host 不替模型选择财务语义。
- repair 通过后仍回到原有 final quality check、finance numeric verifier 和
  synthesis gate 流程；host 只是 terminal contract / provenance gate。

新增结构测试：

- `test_retrieval_finalization_repairs_proxy_answer_when_required_finance_slot_is_missing`
  使用 fake provider 只验证 loop contract：report 仍有
  `property_plant_and_equipment_net` 缺槽时，第一次 proxy `$1.577 billion`
  答案必须被拦截，repair 后输出 `Not separately itemized; ...`。

结构验证：

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest -q \
  tests/test_kernel_v3_phase6_agent_runtime.py \
  tests/test_kernel_v3_phase3_context_compiler.py \
  tests/test_kernel_v3_deep_agent_loop.py \
  tests/test_kernel_v3_loop_tool_dispatch.py \
  tests/test_kernel_v3_retrieval_workbench.py
.venv/bin/python -m py_compile \
  kernel_v3/agent/runtime.py \
  tests/test_kernel_v3_finance_engine.py
```

结果：

- finance engine structural set: `304 passed in 8.61s`
- runtime/context/deep-loop/workbench set: `92 passed in 10.99s`
- `py_compile` passed

说明：这是 mature-loop finalization 合同修复，不是 FinanceBench/FinQA/FAB 分数。
没有新增可报告的 live accuracy。下一步仍应对 `financebench_id_04672` 或同类
missing-slot 类型簇跑 live debug，确认模型在真实工具链中会继续检索或输出正确的
不可得/未单列答案，而不是把 proxy number 当成答案。

## 33. SEC structured fact fallback and target-binding repair checkpoint

继续按“优先照搬成熟 agent loop，不做单题补丁”的原则复盘
`financebench_id_04672`。上一节的 missing-slot gate 生效后，live 仍失败，但
journal 显示模型并不是完全不会做题：

- 一次 live 里模型/semantic numeric judge 已能识别 `$8.738B` 是正确方向；
  host numeric verifier 拒绝的直接原因是 filing 表格里的
  `Dollars/Millions` 缩放没有稳定进入 FinanceFact。
- 后续 live 中 scale 修好了一部分，但 `target_binding` 又把现金流量表
  `Purchases of property, plant and equipment` 错判成 balance-sheet
  `PropertyPlantAndEquipmentNet`，selected facts 变成 `-1.577B/-1.373B/-1.420B`。
- `sec.edgar.financials` 被模型正确调用，但因本机没有有效
  `EDGAR_IDENTITY`，EdgarTools 返回 `edgar_identity_missing`，没有产出
  structured SEC facts；agent 只能继续在 PDF 文本里绕，最后耗尽工具预算。

本轮修复的是通用工具合同和绑定合同：

- `FinanceFactLedger` 的自然文本/表格行抽取新增 nearby filing scale scope
  传播。局部窗口和文档开头都没有 scale 时，会在数值附近向前查找
  `(Millions)`、`amounts in millions`、`dollars in millions` 等 SEC/filing
  表格作用域，并把 `source_scale`、`source_scale_multiplier`、
  `source_scale_applied` 写入 fact metadata。
- `target_binding` 收紧 balance-sheet net PP&E 绑定：cash-flow 语境中的
  `Purchases/Payments to acquire PP&E` 不再能通过
  `property plant and equipment net` 的 line-item / statement match；真正
  `PropertyPlantAndEquipmentNet` concept 或带 `net` 的 balance-sheet 行仍可通过。
- `sec.edgar.financials` 在 EdgarTools 缺失、缺 identity、或 identity 被 SEC
  拒绝时，会 fallback 到官方 `data.sec.gov/api/xbrl/companyfacts` JSON。
  这是官方 SEC/XBRL 候选事实，不是 host 生成答案；LLM 仍负责选择 metric、
  period、line item 和最终表述。
- `_toolchain_candidate_facts` 现在解析 `tool:sec.edgar.financials` 的
  `records`，并把 `fp/start/end/frame/accn` 保留到 candidate fact evidence
  中。这样 model-visible tool-use context 可以直接看到
  `PropertyPlantAndEquipmentNet`、`end=2018-12-31`、`value=8738000000`。

结构验证：

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_open_components.py::test_sec_financials_tool_falls_back_to_official_companyfacts_when_edgartools_unavailable \
  tests/test_kernel_v3_finance_engine.py::test_sec_financials_records_become_candidate_facts_with_period_fields \
  tests/test_kernel_v3_finance_engine.py::test_primary_source_numeric_binding_rejects_cash_flow_ppne_purchase_for_balance_sheet_net_ppne \
  tests/test_kernel_v3_finance_engine.py::test_finance_fact_ledger_propagates_nearby_filing_scale_scope_to_natural_amounts -q
.venv/bin/python -m pytest -q tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest -q \
  tests/test_kernel_v3_finance_open_components.py \
  tests/test_kernel_v3_finance_tool_readiness.py
.venv/bin/python -m py_compile \
  kernel_v3/finance/open_components.py \
  kernel_v3/finance/fact_ledger.py \
  kernel_v3/finance/target_binding.py \
  kernel_v3/agent/runtime.py \
  tests/test_kernel_v3_finance_engine.py \
  tests/test_kernel_v3_finance_open_components.py
```

结果：

- targeted structural/tool-contract tests: `4 passed in 2.09s`
- finance engine structural set: `307 passed in 8.88s`
- finance open-components/readiness set: `31 passed in 4.05s`
- `py_compile` passed
- `git diff --check` passed

真实 SEC 工具 smoke：

```text
sec.edgar.financials(identifier=MMM, statement=balance_sheet, fiscal_year=2018)
status=ok
component=sec_companyfacts_direct
fallback_from=edgar_identity_missing
first record:
concept=PropertyPlantAndEquipmentNet
metric=property plant and equipment net
value=8738000000
unit=USD
fy=2018
fp=FY
form=10-K
end=2018-12-31
accn=0001558370-19-000470
```

live 复测：

```bash
HOLO_V3_LIVE_MODEL=1 .venv/bin/python -m kernel_v3.cli bench finance \
  --dataset .state/kernel_v3/bench/finance/financebench_150_doc_retrieval.jsonl \
  --dev-gold .state/kernel_v3/bench/finance/financebench_150_doc_retrieval.gold.jsonl \
  --offset 1 --limit 1 --parallel 1 \
  --output .state/kernel_v3/bench/finance/fb_debug50_o001_l001_after_sec_fallback_20260618.jsonl \
  --summary-output .state/kernel_v3/bench/finance/fb_debug50_o001_l001_after_sec_fallback_20260618.summary.json \
  --online --planner model --evaluator model --synthesizer model \
  --semantic-intake model --turn-router model \
  --execution-profile finance-capability --mission off \
  --research-profile finance_fundamentals --research-depth deep \
  --live-retrieval --live-search-strategy adaptive --agent-loop-streaming \
  --max-agent-steps 12 --max-agent-tool-calls 24 \
  --max-agent-artifact-bytes 2500000 \
  --live-max-network-fetches 12 --live-download-byte-budget 80000000 \
  --live-timeout-seconds 45 --context-profile provider --profile balanced \
  --thinking disabled --reasoning-effort low --model deepseek-v4-flash \
  --generation-mode auto --latency-target quality --response-language en \
  --progress-events
```

结果：

- `financebench_id_04672`: `status=passed`, `reason=numeric_within_tolerance`
- final answer: `3M's year-end FY2018 net PP&E was $8.738 billion...`
- matched gold numeric: `8.738` vs expected `8.7` within tolerance
- `numeric_verifier_status=passed`
- `verifier_gate=passed`
- `synthesis_gate=passed`
- `sec.edgar.financials` used once
- `finance_fact_count=154`
- `formula_trace_count=2`
- `calculator_call_count=2`
- `tokens=363,559`

说明：这是单道 live debug-row 成绩，gold/reference 没有进入模型上下文；不是
debug50/test100 准确率。它证明本轮修复的是更通用的工具链/agent-loop contract：
官方 SEC structured fact 可以在 open-component 失败边界下继续进入
tool-use context，模型再用 one-shot 工具选择完成 line-item/period binding。

## 10. Structured SEC recovery and noise guard checkpoint

继续调试 `financebench_id_00499` 暴露了下一层 agent-loop 问题：

- 第一轮有效 live 已经取得主来源事实，`primary_source_numeric_binding` 能
  `selected`，但 `finance.slot_bind` 没有产生 calculator payload，finalizer
  提前生成缺槽失败报告。
- 对照成熟 TypeScript agent loop 后，结论是：内部模型工具失败也必须作为可
  恢复 observation 回到工具链，而不能在 finalizer 内部吞掉。
- 本轮新增 `finance.slot_bind failed -> structured SEC recovery -> rebuild
  ledger -> rerun slot_bind` 路径。host 只执行官方 SEC/XBRL 候选事实恢复，
  不选择答案事实、不计算 benchmark 答案，仍由模型重新绑定 slots 和 formulas。
- `sec.edgar.financials` fallback/candidate fact 全链路保留
  `source_uri/source_title/source_kind/taxonomy/fp/start/end/frame`，避免权威
  来源在 tool-use context、ledger、binding 之间丢失。
- 修复结构化工具 payload 噪声：当 `sec.edgar.financials` 已产出 candidate
  facts 时，不再把整个 JSON payload 作为自然语言证据送进 fact ledger。此前
  `cik=66740` 曾被 natural extractor 误抽成 `revenue=66740`，污染模型
  slot binding。

结构测试：

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_open_components.py \
  tests/test_kernel_v3_finance_tool_readiness.py \
  tests/test_kernel_v3_deep_agent_loop.py
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py
git diff --check
```

结果：

- finance engine structural set: `309 passed in 11.64s`
- finance open-components/readiness/deep-loop set: `71 passed in 9.72s`
- targeted structured SEC noise guard tests passed
- `py_compile` passed
- `git diff --check` passed

live 复测：

```bash
HOLO_V3_LIVE_MODEL=1 .venv/bin/python -m kernel_v3.cli bench finance \
  --dataset .state/kernel_v3/bench/finance/financebench_150_doc_retrieval.jsonl \
  --dev-gold .state/kernel_v3/bench/finance/financebench_150_doc_retrieval.gold.jsonl \
  --offset 2 --limit 1 --parallel 1 \
  --output .state/kernel_v3/bench/finance/fb_debug50_o002_l001_after_structured_noise_guard_20260618.jsonl \
  --summary-output .state/kernel_v3/bench/finance/fb_debug50_o002_l001_after_structured_noise_guard_20260618.summary.json \
  --online --planner model --evaluator model --synthesizer model \
  --semantic-intake model --turn-router model \
  --execution-profile finance-capability --mission off \
  --research-profile finance_fundamentals --research-depth deep \
  --live-retrieval --live-search-strategy adaptive --agent-loop-streaming \
  --max-agent-steps 12 --max-agent-tool-calls 24 \
  --max-agent-artifact-bytes 2500000 \
  --live-max-network-fetches 12 --live-download-byte-budget 80000000 \
  --live-timeout-seconds 45 --context-profile provider --profile balanced \
  --thinking disabled --reasoning-effort low --model deepseek-v4-flash \
  --generation-mode auto --latency-target quality --response-language en \
  --progress-events
```

结果：

- `financebench_id_00499`: `status=passed`, `reason=numeric_within_tolerance`
- `sec.edgar.financials=3`
- `calculator.compute=4`
- `formula_trace_count=4`
- `trace_link=100%`, `trace_cite=100%`
- `numeric_verifier_status=passed`
- `verifier_gate=passed`
- `synthesis_gate=passed`
- matched numerics: `5.1%`, `19.8%`, `12.4%`
- `finance_fact_count=40`
- `tokens=175,458`

说明：这是单道 live debug-row 成绩，gold/reference 没有进入模型上下文；不是
debug50/test100 准确率。它证明本轮 agent loop 已经把一个此前反复失败的
FinanceBench 类型推进到可验证闭环：结构化 SEC 工具事实、模型 slot binding、
calculator formula traces、numeric verifier gate 和 final synthesis gate 均可贯通。

## 11. Strict single-agent tool-loop boundary checkpoint

时间点：2026-06-18 CST。用户要求对照成熟 TypeScript agent-loop 项目后，
停止继续依赖 finalizer / preflight 的隐藏金融补算路径，先把单 agent loop
和工具链接口收束成稳定合同。

本轮结论：

- `finance-capability` 的默认合同现在是严格 single-agent tool loop：
  检索、SEC/XBRL、文档解析、slot binding、表格操作、calculator 和
  numeric verifier 必须作为模型请求的 `tool_calls` 出现在 loop 内。
- finalizer 的角色降级为从 loop 观测结果合成、校验和拒绝 unsupported answer；
  它默认不再创建隐藏的 `finance.slot_bind`、`calculator.compute` 或 SEC
  recovery 结果来补齐模型没做完的公式题。
- 兼容路径仍存在，但必须显式设置
  `agent_loop.finalizer_numeric_preflight=true`，用于老结构测试，不作为
  finance-capability 默认做题路径。
- `finance_agent_loop_contract()` 新增 `tool_execution_boundary` 和
  `finalization_boundary`，并通过 runtime compact、provider prompt 和
  `assistant.turn.single_agent_tool_loop_contract` 暴露给模型。模型每轮都能看到：
  金融数值答案需要在 final answer 前通过 evidence / slot bind / calculator
  或 table query / verifier 形成可观察工具结果。
- `_synthesize_retrieval_final(...)` 在 strict loop 下只写
  `finance_fact_ledger` 和 `finance_numeric_preflight(status=skipped,
  reason=single_agent_tool_loop_contract)`，不会再调用隐藏 numeric preflight。
- 后续代码审查继续切断 legacy 干扰：`_RecipeEvaluator` 在 strict single-agent
  loop 下不再调用 legacy `plan_finance_formula(...)` 来决定是否阻止 final。
  strict 路径只根据模型可见 `finance_question_requirements`、真实 evidence、
  已有 calculator / verifier observations 和 model-compiled execution program
  发出工具需求反馈，例如 `finance_loop_tool_required:calculator.compute`、
  `finance_loop_tool_required:finance.verify_numeric`。旧公式规划器只允许非
  strict/legacy 路径使用。

涉及代码：

- `kernel_v3/agent/execution_profile.py`
- `kernel_v3/agent/runtime.py`
- `kernel_v3/deep_loop.py`
- `kernel_v3/finance/tool_catalog.py`
- `tests/test_kernel_v3_deep_agent_loop.py`
- `tests/test_kernel_v3_finance_engine.py`
- `tests/test_kernel_v3_finance_open_components.py`

结构验证：

```bash
.venv/bin/python -m py_compile \
  kernel_v3/deep_loop.py \
  kernel_v3/agent/runtime.py \
  kernel_v3/finance/tool_catalog.py

.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py -q
.venv/bin/python -m pytest \
  tests/test_kernel_v3_finance_open_components.py \
  tests/test_kernel_v3_finance_tool_readiness.py \
  tests/test_kernel_v3_execution_profile.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
```

结果：

- `py_compile` passed
- deep loop structural set: `41 passed in 3.67s`
- finance open-components/readiness/profile set: `50 passed in 5.24s`
- finance engine structural set: `310 passed in 8.45s`
- strict legacy-separation follow-up: targeted tests passed; wider regression
  passed with `91` loop/tool/profile tests and `311` finance-engine tests.

说明：这是 agent-loop 合同和工具接口边界修复，不是 FinanceBench/FAB/FinQA
准确率。下一步应在 debug50 类型簇做小批 live runs，检查模型是否真正把
`sec.edgar.financials`、`document.*`、`finance.slot_bind`、
`calculator.compute`、`data.table.query` 和 `finance.verify_numeric` 组合成
loop 内闭环，而不是依赖 finalizer 兜底。

## 12. Numeric verification prompt contract after live miss

时间点：2026-06-18 CST。用户要求先做出一道题；随后对
`financebench_id_00499` 做了当前 strict single-agent loop 的单题 live 复测：

```bash
HOLO_V3_LIVE_MODEL=1 .venv/bin/python -m kernel_v3.cli bench finance \
  --dataset .state/kernel_v3/bench/finance/financebench_150_doc_retrieval.jsonl \
  --dev-gold .state/kernel_v3/bench/finance/financebench_150_doc_retrieval.gold.jsonl \
  --offset 2 --limit 1 --parallel 1 \
  --output .state/kernel_v3/bench/finance/fb_debug50_o002_l001_current_single_20260618.jsonl \
  --summary-output .state/kernel_v3/bench/finance/fb_debug50_o002_l001_current_single_20260618.summary.json \
  --online --planner model --evaluator model --synthesizer model \
  --semantic-intake model --turn-router model \
  --execution-profile finance-capability --mission off \
  --research-profile finance_fundamentals --research-depth deep \
  --live-retrieval --live-search-strategy adaptive --agent-loop-streaming \
  --max-agent-steps 12 --max-agent-tool-calls 24 \
  --max-agent-artifact-bytes 2500000 \
  --live-max-network-fetches 12 --live-download-byte-budget 80000000 \
  --live-timeout-seconds 45 --context-profile provider --profile balanced \
  --thinking disabled --reasoning-effort low --model deepseek-v4-flash \
  --generation-mode auto --latency-target quality --response-language en \
  --progress-events --thread-prefix fb-single-current-20260618
```

结果：

- `status=failed`
- `reason=numeric_outside_tolerance`
- `retrieval_run_count=0`
- `calculator_call_count=0`
- `formula_trace_count=0`
- `transform_plan_count=0`
- `missing_slots=["operating_cash_flow","property_plant_and_equipment_net","net_income"]`
- tool observations included `sec.edgar.financials`, `document.docling.convert`,
  and `artifact.read`, so this was not "no tool call"; the missing part was the
  numeric transform/verification tool chain.

结论：

- 模型拿到了 raw filing inputs，例如 capex、revenue、PPE、assets，但没有把
  FY2022 capital-intensity task 转成比率公式输出。
- 它给出了定性判断而没有输出 `capex/revenue`、`PPE/assets`、`ROA` 等
  scorer 所需 derived numerics。
- 更深层问题是 prompt/contract 没有足够明确地告诉 agent loop：
  数值金融题必须使用哪些工具完成验证。

本轮 prompt/contract 修复：

- `kernel_v3/processors/contracts.py`
  - 在 Standard tool interface 中显式描述：
    `finance.slot_bind` 用于模型拥有的 slot/formula binding；
    `calculator.compute` 用于 deterministic transforms；
    `finance.verify_numeric` 用于 final material numeric claims。
  - 在 Finance-capability prompt 中新增 concrete verification sequence：
    authoritative evidence -> `finance.slot_bind` -> `calculator.compute` /
    `data.table.query` -> `finance.verify_numeric` -> final response。
  - 明确禁止用 raw source numbers 替代 requested derived metric。
- `kernel_v3/deep_loop.py`
  - `assistant.turn.single_agent_tool_loop_contract` 的
    `required_for_finance_numeric_answers` 现在列出
    `finance.slot_bind`、`calculator.compute`/`data.table.query`、
    `finance.verify_numeric`。
  - `stop_rule` 明确：当工具可用且输入已出现时，finance calculation /
    ratio / efficiency / ranking / margin / growth / multiple / bps /
    comparison 题不能缺 `calculator.compute` 和 `finance.verify_numeric`
    observations 就 final。
- `kernel_v3/processors/adapters.py`
  - synthesizer prompt 也携带同一条规则：只有 raw filing inputs 而没有
    FormulaTrace / verification 时，不得把 qualitative-only answer 当成完整答案。
- `kernel_v3/finance/tool_catalog.py`
  - runtime compact 的 `finance_agent_loop_contract` 同步暴露
    `calculator.compute FormulaTrace` 和 `finance.verify_numeric observation`
    为 final answer required elements。

结构验证：

```bash
.venv/bin/python -m pytest \
  tests/test_kernel_v3_phase5_semantic_processors.py::test_phase5_finance_prompt_exposes_numeric_verifier_tool_example \
  tests/test_kernel_v3_phase5_semantic_processors.py::test_phase5_finance_prompt_names_numeric_verification_tool_sequence \
  tests/test_kernel_v3_phase5_semantic_processors.py::test_phase5_synthesizer_prompt_uses_evidence_and_citation_previews_not_raw_bodies \
  tests/test_kernel_v3_finance_engine.py::test_finance_capability_provider_compact_preserves_one_shot_tool_surface \
  tests/test_kernel_v3_finance_engine.py::test_finance_capability_assistant_turn_prompt_exposes_stop_and_answer_contract \
  tests/test_kernel_v3_deep_agent_loop.py::test_assistant_turn_prompt_exposes_strict_finance_single_agent_loop_contract -q
```

结果：`6 passed in 1.58s`。

说明：这是 prompt/contract structural regression，不是 live benchmark pass。
下一步需要重新跑 live 单题来确认模型是否实际调用
`finance.slot_bind` / `calculator.compute` / `finance.verify_numeric`。
