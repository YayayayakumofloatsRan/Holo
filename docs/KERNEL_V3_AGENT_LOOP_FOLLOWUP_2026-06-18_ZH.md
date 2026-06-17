# Kernel v3 Agent Loop Follow-Up 2026-06-18

状态：已完成一轮通用 agent loop 合同修复；结构测试通过；live 复测因权限审核超时未完成，不能报告为金融准确率提升。

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
