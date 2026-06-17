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
