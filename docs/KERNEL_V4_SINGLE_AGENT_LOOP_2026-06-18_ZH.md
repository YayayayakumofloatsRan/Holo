# Kernel v4 单 Agent 循环改写记录

日期：2026-06-18

分支：`kernel-v4`

## 结论

Kernel v4 走新的架构线：参考用户提供的成熟 TypeScript 项目，把核心单 agent loop 用 Python 改写一遍。v4 第一阶段不做多 agent、不做子 agent、不做 v3 的金融语义状态机。

目标是先得到一个干净、通用、可审查的循环：

1. 模型输出文本和 `tool_call`。
2. Host 按工具协议执行。
3. Tool result 立即回灌到下一轮模型上下文。
4. 大工具结果转为 artifact，模型可用 `artifact.read` 读取。
5. 工具发现由 `tool.discovery` 提供合同，不由本地逻辑替模型决定下一步。
6. 循环退出只由模型最终回答、预算、硬错误或明确阻塞决定。

## 删除的 v3 闸门

v4 active loop 不加载这些金融语义闸门：

- `FactLedger`
- `SlotFrame`
- `finance.slot_bind`
- 本地 “missing slots 必须补齐后才能计算” gate
- host 侧任务编译后强制补槽状态机

它们不是“降级为辅助”，而是不进入 v4 单 agent 主循环。v4 的原则是：模型看到检索/SEC/文档搜索/表格/上下文解析结果后，可以直接选择输入并调用 `calculator.compute`、`data.table.query`、`finance.verify_numeric`。

## 参考框架对应关系

用户提供的参考项目关键部件：

- `query.ts`：主 query loop。
- `StreamingToolExecutor.ts`：流式工具执行，支持并发安全工具并行、非并发工具独占。
- `ToolUseContext`：携带消息、工具、权限、进行中工具、上下文修改。
- `toolResultStorage.ts`：大工具结果持久化和上下文替换。
- `toolSearch.ts`：工具发现和 deferred tool surface。

Kernel v4 的 Python 对应实现：

- `kernel_v4/loop.py`：`SingleAgentLoop`。
- `kernel_v4/tooling.py`：`ToolRegistry`、`StreamingToolExecutor`、`tool.discovery`、`artifact.read`。
- `kernel_v4/context.py`：`ToolUseContext`、大 tool result artifact replacement。
- `kernel_v4/runtime.py`：`AbortController`、`WorkflowObserver`、`ContextEdit`、`ToolLifecycleRecord`。
- `kernel_v4/monitoring.py`：实时 workflow 事件渲染，支持人读 compact 输出和机器读 JSONL。
- `kernel_v4/contracts.py`：消息、工具调用、工具结果、模型事件、循环结果协议。
- `kernel_v4/prompts.py`：通用单 agent prompt 和金融特调 prompt。
- `kernel_v4/finance_tools.py`：成熟金融工具后端适配，不引入 `finance.slot_bind`。
- `kernel_v4/providers.py`：OpenAI-compatible / DeepSeek live provider，支持原生 function tool schema、provider-native `tool_choice` 强制工具、streaming tool-call delta 解析和 v4 工具名回映射。
- `kernel_v4/live_smoke.py`：最小 live provider smoke 入口，可用 `--force-tool calculator.compute` 验证真实 provider 工具闭环；默认只强制第 1 个模型 turn，后续 turn 恢复模型自主回答。

## 运行时控制与可视化

2026-06-18 的第二次 v4 架构补齐，优先复刻参考项目的运行时控制面，而不是进入做题：

- `AbortController` / `AbortSignal`：外部 runner 或 UI 可以中止当前 loop。loop 在模型 turn 前、模型 turn 后、工具执行前后检查 abort 状态。
- tool cancel 补偿：如果 abort 发生在工具调用已经出现之后，host 会生成 `holo.kernel_v4.tool_cancelled.v1` synthetic tool result，避免留下孤立 `tool_call`。
- `ContextEdit`：工具或 host 可以通过 `context.apply_edit(...)` 修改运行上下文，例如设置 metadata、追加消息、删除 artifact。后续模型 turn 的 `workflow` 上下文会看到最近 edits 和 metadata keys。
- `ToolLifecycleRecord`：每个工具调用记录 `queued -> executing -> completed/failed/cancelled -> yielded` 生命周期，并记录 artifact/error/cancel reason。
- `WorkflowObserver`：所有关键 loop 事件会实时发给 callback。`live_smoke` 支持 `--show-workflow` 输出内部工作流。
- `WorkflowConsoleMonitor`：默认 compact 模式把 text delta 聚合为 `assistant_stop text_chars=N`，突出 `model_start`、`assistant_tool_call`、`tool_start`、`tool_result`、`loop_completed/failed`；`--workflow-format jsonl` 保留完整机器可读事件。

这部分是通用 agent loop 能力，不绑定 FinanceBench，也不引入金融规则 gate。

## Streaming Tool Executor 改写

2026-06-18 的第三次 v4 架构补齐继续对齐参考项目的 streaming executor：

- provider 不再等完整 response 才交出工具调用。OpenAI-compatible / DeepSeek SSE delta 在函数名和 JSON 参数完整后立即发出 v4 `tool_call` 事件。
- provider 的阻塞 SSE 读取进入单独 producer thread，通过 asyncio queue 持续推送 chunk，避免阻塞 Python event loop。
- `SingleAgentLoop` 在消费模型流时立即把 `tool_call` 交给 `StreamingToolExecutor`，工具可以在 `assistant_message_stop` 前启动和完成。
- loop 在模型流消费期间持续 drain 已完成工具结果；模型流结束后再 drain remaining results，保持参考框架“streaming 中执行，turn 结束前补齐 tool_result”的核心语义。
- `tool.discovery` 会把发现到的 deferred tools 写入 `ContextEdit(metadata.set: discovered_tool_names)`；下一轮 `ToolRegistry.manifests(...)` 会把这些工具真正暴露到 provider-native tool surface，而不是只放在文本说明里。
- `live_smoke --show-workflow` 已能看到 `assistant_tool_call -> tool_queued -> tool_start -> tool_lifecycle(completed) -> assistant_message_stop -> tool_result` 的实时顺序。

这一步仍然没有改变核心思路：模型决定工具，host 只执行、记录、补齐生命周期、管理上下文。

## 金融工具面

v4 金融模式暴露普通工具，不暴露本地语义闸门：

- `finance.toolchain.describe`
- `sec.edgar.company_filings`
- `sec.edgar.financials`
- `document.docling.convert`
- `document.trafilatura.extract`
- `document.search.hybrid`
- `provided_context.parse`
- `market.openbb.fetch`
- `data.table.query`
- `math.sympy.compute`
- `calendar.days_between`
- `calculator.compute`
- `finance.verify_numeric`
- `artifact.read`
- `tool.discovery`

当前实现复用 v3 已经接好的成熟工具 wrapper 作为后端，包括 EdgarTools、Docling、Trafilatura、BM25/DuckDB/Pandas/SymPy、calculator 和 numeric verifier，但不复用 v3 agent runtime/evaluator/slot gate。

## 测试结果

本次提交前执行的是结构测试，不代表 FinanceBench/FQA 真实做题能力：

```text
.venv/bin/python -m py_compile kernel_v4/__init__.py kernel_v4/contracts.py kernel_v4/context.py kernel_v4/tooling.py kernel_v4/prompts.py kernel_v4/loop.py kernel_v4/finance_tools.py tests/test_kernel_v4_single_agent_loop.py
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py -q
5 passed
```

接入 live provider 后，结构测试扩展为：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_live_provider.py -q
17 passed
.venv/bin/python -m pytest tests/test_kernel_v4_monitoring.py -q
2 passed
```

测试覆盖：

- 工具结果能进入下一轮模型上下文。
- v4 金融工具面不含 `finance.slot_bind`。
- 金融 prompt 明确删除本地 `FactLedger` / `SlotFrame` / slot-bind gate。
- 大工具结果会 artifact 化并保持可读。
- `tool.discovery` 返回工具合同而不是语义答案。
- OpenAI-compatible provider 会把 v4 tools 转成原生 function tools。
- provider 可以把 v4 工具名强制投射到 provider-native `tool_choice`。
- streaming tool-call delta 能映射回 v4 原工具名。
- provider packet preview 不暴露 API key。
- workflow callback 可以实时看到 model/tool/loop 事件。
- abort 可以取消运行中的工具，并生成 synthetic tool result。
- context edit 会进入下一轮模型请求上下文。
- streamed tool_call 会在模型流结束前启动工具执行。
- tool.discovery 发现到的 deferred tool 会在下一轮进入 provider-visible tool surface。
- compact workflow monitor 会聚合文本增量，避免实时监控刷屏；JSONL 模式仍保留完整事件。

已完成的最小 live smoke：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --max-turns 3 --max-tool-calls 4
{"status": "completed", "answer": "v4 live provider ok.", ...}
```

已完成的 provider-native 工具闭环 smoke：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --finance-tools --force-tool calculator.compute --max-turns 4 --max-tool-calls 8 --prompt "Use the forced calculator.compute tool to calculate 2+2. After the tool result, answer with the numeric result and say it came from calculator.compute."
{"status": "completed", "answer": "The numeric result is **4**, and it came from **calculator.compute**.", "tool_call_count": 1, "turn_count": 2, ...}
```

改写 streaming executor 后，新的 live workflow smoke 证明工具会在模型流结束前启动：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --calculator-only --tool-choice none --force-tool calculator.compute --show-workflow ...
assistant_tool_call -> tool_queued -> tool_start -> tool_lifecycle(completed) -> assistant_message_stop -> tool_result
```

这个 live workflow 是架构联通证据，不是 FinanceBench/FQA 做题成绩；是否最终答对仍以后续 live benchmark 为准。

compact 监控输出示例：

```text
.venv/bin/python -m kernel_v4.live_smoke --model deepseek-chat --max-turns 2 --max-tool-calls 2 --show-workflow
    0.00s t0 loop_start run=run-... thread=kernel-v4-live-smoke
    0.00s t1 model_start messages=1 tools=2
    1.95s t1 assistant_stop text_chars=20
    1.95s t1 loop_completed answer_chars=20
```

## 下一步

下一步不是继续补 v3 闸门，而是把 live debug runner 接到 `SingleAgentLoop`：

1. 用 `python -m kernel_v4.live_smoke --finance-tools --force-tool calculator.compute` 验证真实 provider 工具调用闭环。
2. 接 live retrieval/SEC 网络权限。
3. 让 FinanceBench debug item 通过 v4 loop 做一题。
4. 用 live 结果验证 calculator 和 verifier 是否由模型主动调用。
5. 再扩展到 debug50 类型分组测试。
