# Kernel v3 External Agent Loop Parity Audit 2026-06-17

状态：深度审查记录。本文只审查外部 TypeScript agent-loop 项目与 Holo Kernel v3 的结构差距，不声明 FinanceBench / FinQA / FAB 金融做题成绩。

外部项目路径：

`/mnt/d/COURSES/人工智能算法实践/code-main/code-main`

Holo 当前审查范围：

- `kernel_v3/deep_loop.py`
- `kernel_v3/tool_use.py`
- `kernel_v3/tools.py`
- `kernel_v3/processors/providers.py`
- `kernel_v3/agent/runtime.py`
- `kernel_v3/finance/open_components.py`
- `kernel_v3/finance/tool_catalog.py`
- `tests/test_kernel_v3_deep_agent_loop.py`
- `tests/test_kernel_v3_tool_use.py`
- `tests/test_kernel_v3_finance_tool_readiness.py`

## 一句话结论

Holo 已经从旧的一步一工具循环，升级到“单回合多工具 + tool.discovery + artifact.read + ToolUseContext + artifact 化长结果”的深循环骨架。

但与外部成熟项目相比，Holo 还没有完成真正的 streaming agent loop。当前 Holo 仍是：

`完整 JSON assistant.turn -> 批量执行工具 -> observation 回流`

外部项目的成熟路径是：

`provider streaming delta -> tool_use 块一出现就入队执行 -> progress/result 立即回流 -> 缺失/取消/失败 tool_result 全部补齐 -> 下一轮继续`

所以，Holo 现在的核心缺口不是再加某一道题的规则，而是把工具调用从“离线批处理”推进到“流式、可中断、预算稳定、可恢复”的工作台。

## 外部项目做对的事情

### 1. Query loop 是真正的流式工具循环

外部项目核心在 `src/query.ts`：

- 每次 query 进入模型 streaming。
- streaming 中每收到 assistant message，就扫描其中的 `tool_use` block。
- `tool_use` 一出现，马上交给 `StreamingToolExecutor.addTool(...)`。
- 同时持续 drain `getCompletedResults()`，工具结果可以在模型流结束前后逐步返回。
- 如果 provider fallback、异常、用户中断发生，会给已经出现但没完成的 tool_use 生成 synthetic tool_result，避免协议断裂。

这不是简单的“多工具”。它保证了一个更强的不变量：

每个模型发出的 tool_use，最终都必须有一个对应的 tool_result，无论成功、失败、取消、fallback、异常还是用户中断。

### 2. StreamingToolExecutor 有真实调度语义

外部项目 `src/services/tools/StreamingToolExecutor.ts` 体现了几个成熟点：

- 并发安全工具可以并行。
- 非并发安全工具独占执行。
- 结果按必要顺序 yield。
- progress message 可以立即 yield。
- sibling error 可以取消尚未完成的 sibling。
- 对可中断工具，有 child abort controller。
- streaming fallback 会 discard 当前 attempt 的 pending / running results，避免 orphan tool_result 混入新 attempt。

Holo 目前的 `kernel_v3/tool_use.py` 只实现了 completed assistant turn 下的 evented batch executor。它可以记录 queued / started / completed，但还不是 provider-streaming executor。

### 3. Tool contract 很厚

外部项目 `src/Tool.ts` 的工具接口不仅是 name/schema/permission。它包含：

- `inputSchema`
- `inputJSONSchema`
- `outputSchema`
- `isConcurrencySafe(input)`
- `isReadOnly(input)`
- `isDestructive(input)`
- `isOpenWorld(input)`
- `requiresUserInteraction()`
- `interruptBehavior()`
- `maxResultSizeChars`
- `shouldDefer`
- `alwaysLoad`
- `validateInput`
- `checkPermissions`
- `mapToolResultToToolResultBlockParam`
- `renderToolUseProgressMessage`
- `contextModifier`

这些字段决定了 agent loop 能不能泛化。Holo 当前 `ToolManifest` 只有 name/version/resource/operator/side_effect/permissions/enabled/description/input_schema，调度和预算能力仍然偏薄。

### 4. 大工具结果预算是跨回合稳定的

外部项目 `src/utils/toolResultStorage.ts` 有两层机制：

- 单个工具结果过大时，写入 session tool-results 文件，模型只看 preview + file path。
- 同一个 API user message 中多个 tool_result 的总量超预算时，按 `tool_use_id` 选择并持久替换大结果。

更重要的是它维护 `ContentReplacementState`：

- `seenIds` 记录哪些 tool_use_id 已经处理过。
- `replacements` 记录被替换后的精确 preview 文本。
- resume / compact / fork 后用相同 replacement，保持 prompt cache 前缀稳定。

Holo 当前有 `ArtifactStore`、`content_projection`、`artifact.read`，并且金融开放组件已把长 SEC/document/table/market payload 写 blob。本次 P0 接入又新增了 batch observation 层的 `ToolResultReplacementState` 雏形。但它还没有达到外部项目的成熟度：replacement 尚未在 provider 发包前统一应用，也没有完整的 tool-results 文件持久化与 provider-cache 级字节稳定策略。

### 5. Tool discovery 是 deferred tool loading

外部项目的 Tool Search 不是简单查工具清单：

- 工具可声明 `shouldDefer` / `alwaysLoad`。
- 根据 deferred tool 描述 token 成本，自动决定是否启用 tool search。
- 模型可用 ToolSearchTool 检索 deferred tools。
- exact select、MCP server prefix、keyword scoring 都有处理。
- 工具池排序关注 prompt cache stability，built-in tools 保持稳定前缀。

Holo 当前 `tool.discovery` 是有价值的，但只是对已注册 allowed manifests 做 substring scoring。它还不是 token-aware deferred loading。

## Holo 已完成的部分

### 1. 单回合多工具骨架

`kernel_v3/deep_loop.py` 已经支持 `assistant.turn`：

- 一个 assistant turn 可包含多个 tool_calls。
- 每个 tool call 有稳定 `tool_call_id`。
- tool call 被转为 `CandidateAction` 后仍走 `PolicyGate` / `ToolRegistry`。
- malformed tool call 会成为 `tool_call_parse_error` observation，进入下一轮 replanning。
- 每个 batch 生成 `tool_batch_result` observation，保留 tool_call_id、status、artifact refs、content_projection。

这是正确方向。

### 2. 工具发现和 artifact 读取

`kernel_v3/tool_use.py` 已经提供：

- `tool.discovery`
- `artifact.read`
- `ToolUseContext`
- `ToolExecutionEvent`
- `ToolResultProjection`
- `StreamingToolExecutor`

这解决了“工具入口模型可见”和“长结果可延迟读取”的基础问题。

### 3. 金融工具长结果 artifact 化

`kernel_v3/finance/open_components.py` 当前已让 SEC/EDGAR、Docling、Trafilatura、OpenBB、DuckDB table query 在 runtime 提供 `ArtifactStore` 时写入完整 JSON blob。

模型上下文只接收：

- bounded observation
- `artifact_id`
- `artifact_uri`
- `artifact_kind`
- `full_payload_artifact_id`
- `artifact_read_hint`

这对 UbuntuHolo 稳定性和上下文预算是必要进步。

### 4. FB/FQA 工具面 preflight

`kernel_v3/finance/tool_readiness.py` 已经能检查 FB/FQA 相关工具是否：

- allowed by recipe
- registered
- provider visible
- planner prompt visible
- policy allowed
- component binding 可用

这不是 benchmark 成绩，但能防止“模型根本看不到工具”的低级失败。

## 还差什么

### P0. Provider-native streaming tool-use

当前 `kernel_v3/processors/providers.py` 的 `OpenAICompatibleProvider` 固定：

```json
"stream": false
```

并使用 JSON response_format。Holo 的 deep loop 只能等完整 `assistant.turn` JSON 返回后再执行工具。

需要做：

- 给 `ProcessorProvider` 增加 streaming event 接口。
- 支持 provider SSE / chunked response。
- 解析 assistant text delta、tool_call/tool_use delta、finish/fallback/error event。
- 将 tool_use delta 直接喂给 Holo `StreamingToolExecutor`。
- fallback 或 provider error 时，为所有已出现但未完成的 tool_call 生成 synthetic observation。
- 保留 JSON `assistant.turn` 作为 fallback，不要一次性切断现有路径。

这是 Holo 与成熟 agent loop 最大的差距。

### P0. ToolManifest 升级为完整调度合同

`ToolManifest.runtime` 和 `ToolRuntimeSpec` 已经接入第一层，但合同还没有完全支配 executor、interrupt、deferred loading 和 provider tool exposure。

`ToolRuntimeSpec` 已有字段雏形，仍需补齐并接入这些调度语义：

- `concurrency_safe`
- `read_only`
- `destructive`
- `open_world`
- `requires_user_interaction`
- `interrupt_behavior`: `cancel | block`
- `max_result_size_chars`
- `result_persistence_policy`
- `should_defer`
- `always_load`
- `progress_supported`
- `timeout_seconds`
- `idempotent`

这不是形式主义。没有这些字段，agent loop 无法稳定决定并发、取消、prompt 暴露和结果预算。

### P0. 跨回合工具结果预算状态

Holo 当前 artifact 化解决了“单次长 payload 不塞上下文”，本次新增的 `ToolResultReplacementState` 解决了 batch observation preview 的一部分稳定替换问题，但还没解决：

- 同一个 batch 中多个 tool results 总量超预算。
- 已经给模型看过的结果，下一轮是否还能替换。
- compact/resume 后 replacement 是否字节级稳定，是否保护 provider cache。

需要把当前 `ToolResultReplacementState` 推进到类似外部项目 `ContentReplacementState` 的完整结构：

- keyed by `tool_call_id` / `artifact_id`
- `seen_ids`
- `replacement_by_id`
- `full_payload_ref`
- `first_visible_projection_hash`
- resume reconstruction
- journal / thread 持久化

这直接关系到长任务成本和上下文稳定性。

### P1. Executor 支持 progress、running abort 和 async generator 工具

Holo 当前工具执行是同步 `ToolRegistry.execute_with_artifacts()`，executor 用 `ThreadPoolExecutor` 包了一层。它还不能：

- 工具内部产生 progress observation。
- streaming yield progress 给 CLI / journal。
- 对 running tool 进行真实 abort。
- 区分 interruptBehavior=cancel/block。
- 对 subprocess / network fetch 传入 abort signal。

金融做题时，Docling、OpenBB、SEC、crawl、script 都可能是长工具。没有 progress 和 abort，用户看到的就是“系统卡住”，UbuntuHolo 稳定性也更难管。

### P1. Tool discovery 需要从“搜索 manifest”升级成 deferred loading

Holo 当前 `tool.discovery` 是必要的，但还不够成熟。

需要：

- 工具声明 `should_defer` / `always_load`。
- 按 provider context window 和工具描述 token 成本自动决定初始暴露集合。
- 支持 exact `select:<tool_name>`。
- 支持 BM25 / keyword / family ranking。
- 对 finance 工具按 task family 分组返回。
- 保持 built-in / core finance tools 的稳定 prompt 前缀，保护 cache。

否则工具越多，prompt 会越来越重；工具少，又会看不到能力。

### P1. 工具结果对 context 的结构化修改能力

外部工具支持 `contextModifier`。Holo 目前主要靠 journal + context compiler 重新投影。

金融任务需要一种更明确的 workbench state：

- 当前目标公司/期间
- 已绑定 source documents
- candidate facts
- extracted tables
- unresolved slots
- formula requests
- artifact refs
- verifier failures

现在 Holo 有 finance working state，但来源分散在 runtime 中很多 helper。下一步应把它抽成明确的 `FinanceWorkbenchState` 或通用 `TaskWorkbenchState`，由工具 observation 显式更新，而不是靠 planner prompt 猜 recent_observations。

### P1. 原生 tool/function-calling 与 JSON fallback 双轨

Holo 当前要求模型返回 JSON `assistant.turn`。这可控，但会牺牲 provider 原生 tool-call 的 schema 约束、streaming delta 和生态兼容。

应保留两条路径：

- provider 支持原生 tools：使用原生 tool/function-calling。
- provider 不支持或出错：退回 JSON `assistant.turn`。

金融做题依赖工具参数质量，原生 schema 能减少很多 malformed payload。

### P2. 可视化和运行控制

用户明确要求进程可视化。Holo 目前 journal 中有 tool_execution_event，但还需要：

- CLI 实时显示当前 step / tool_call_id / tool / status / elapsed / artifact size。
- 区分 queued / running / completed / cancelled / failed。
- 长工具 progress event。
- benchmark runner 的 item-level live progress 与 processor/tool breakdown。
- 卡住时能看到是 provider、SEC、Docling、OpenBB、script 还是 verifier。

这是迭代效率问题，不是 UI 装饰。

### P2. Live debug50 类型化评测闭环

当前结构测试不能说明金融能力。下一阶段必须回到 live debug50，但方式不能逐题修补。

应按任务族跑：

- direct line item / disclosure extraction
- defined formula numeric calculation
- computed business judgment
- driver attribution / bridge adjustment
- table ranking / comparison
- market/macro context
- FinQA table/program-like transforms

每个失败归因到：

- tool not visible
- tool payload malformed
- source acquisition failed
- extraction/table conversion failed
- slot binding failed
- formula trace wrong
- verifier blocked correctly
- synthesis unsupported
- context budget/dropout
- provider/tool timeout

只有这样才能判断系统性缺口，而不是继续逐题打补丁。

## 对当前 Holo 的理论能力判断

现在 Holo 理论上已经接近“可组装金融工作台”，但还不能说 loop 完美。

已具备：

- 多工具 turn。
- 工具 discovery。
- artifact 延迟读取。
- 金融工具面。
- slot_bind / calculator / numeric verifier。
- 长 payload artifact 边界。
- preflight 审计。

未闭合：

- provider streaming tool-use。
- running tool abort / progress。
- 厚工具合同的全链路执行语义。
- token-aware deferred tool loading。
- provider 发包前的跨回合稳定 result replacement。
- 类型化 live debug50 闭环结果。

所以，最诚实的状态是：

Holo 已经摆脱“一题一补丁”的最低级循环，但还没完成成熟 agent loop 的关键工程层。下一次迭代不应该再碰金融规则，而应把本轮 P0 骨架继续闭合：streaming provider tool-use、ToolRuntimeSpec 的执行语义、ContentReplacementState 级结果预算。

## 建议实现顺序

1. 继续补齐 `ToolRuntimeSpec`，让 manifest 可表达的调度/预算字段真正支配 executor、interrupt 和 provider tool exposure。
2. 将剩余 `concurrency_safe` 兼容读法收口到 runtime spec，避免新工具继续把调度字段塞进 input schema。
3. 为 `ToolRegistry` 增加 async/progress 执行协议，旧同步 executor 自动包装。
4. 将当前 `ToolResultReplacementState` 升级为完整 `ContentReplacementState` 等价物，让 tool batch result projection、artifact persistence、journal reconstruction 和 provider 发包前 replacement 跨回合稳定。
5. 扩展已新增的 `ProcessorProvider` streaming event 协议，从 structural tests 推进到 deep loop 可消费的事件源。
6. 完成 OpenAI-compatible / DeepSeek provider 的 SSE streaming 与 tool-call delta normalization。
7. 将 deep loop 从 completed-turn batch 模式升级为 streaming tool-use 模式，JSON assistant.turn 作为 fallback。
8. CLI 显示 tool execution progress。
9. 跑 live debug50，按任务族归因，不做 fake score。

这条路线完成后，Holo 才能更接近外部成熟项目的通用 agent loop，同时保持 Kernel v3 的 host-owned 验证、journal、artifact、gold isolation 和 LLM-owned semantic judgment 不变量。

## 2026-06-17 代码级复审补充

本节记录本次复审看到的直接代码证据。结论没有变化：Holo 的方向正确，但 P0 还没有闭环。

### 外部项目的真实控制流

外部项目每轮发包前先治理上下文。`src/query.ts:365-394` 先从 compact boundary 后的消息投影开始，调用 `applyToolResultBudget(...)`，并按 `querySource` 决定是否把 replacement 记录回 transcript。随后 `src/query.ts:412-454` 继续做 microcompact、context collapse 和 autocompact。这说明它把“上下文预算稳定性”放在 provider 调用之前，而不是等失败后补救。

外部项目的 provider streaming loop 在 `src/query.ts:708-860`。模型流中每收到 assistant message，立即抽取 `tool_use` block，并在 `src/query.ts:837-843` 调用 `streamingToolExecutor.addTool(...)`。同时 `src/query.ts:847-860` 非阻塞 drain 已完成工具结果。这是 Holo 当前缺少的 provider-native streaming tool-use。

外部项目在 `src/query.ts:712-740` 处理 streaming fallback：清空 orphan assistant/tool result 状态，并 discard 旧 executor，防止旧 attempt 的 tool_result 混入新 attempt。Holo 当前没有等价的不变量，因为 Holo 还没有 provider streaming attempt。

外部项目在 `src/query.ts:1360-1370` 后进入工具执行收尾；如果 streaming executor 已经启用，就继续 drain `getRemainingResults()`，否则退回传统 `runTools(...)`。这说明它同时保留了 streaming path 和 batch fallback path，Holo 也应该采用双轨迁移，而不是一次性替换现有 JSON turn。

### 外部项目的 executor 不变量

`src/services/tools/StreamingToolExecutor.ts:34-40` 明确声明 executor 的语义：工具随 streaming 到达而执行，并在必要时保持结果顺序。`src/services/tools/StreamingToolExecutor.ts:76-124` 显示 `addTool(...)` 不是简单入列表，而是解析输入、判定并发安全、入队并立即 `processQueue()`。

`src/services/tools/StreamingToolExecutor.ts:129-150` 的调度规则是：没有工具在运行，或当前工具和所有运行工具都并发安全时才可执行；非并发安全工具阻塞队列。这是可泛化调度合同，不是金融题规则。

`src/services/tools/StreamingToolExecutor.ts:153-205` 为 sibling error、用户中断、streaming fallback 都生成 synthetic `tool_result`。这条不变量很重要：模型发出的每个 `tool_use` 必须最终对应一个成功、失败、取消或 fallback 的结果。Holo 当前只对 completed JSON turn 的 parse error / policy block / guard block 有 observation，还没有 provider-native `tool_use_id -> tool_result` 配对层。

`src/services/tools/StreamingToolExecutor.ts:207-241` 根据 `interruptBehavior()` 决定用户新消息到来时工具是 cancel 还是 block。Holo 新增的 `ToolRuntimeSpec.interrupt_behavior` 只是雏形，尚未接入 executor。

### 外部项目的 tool result budget 不变量

`src/utils/toolResultStorage.ts` 定义的 `ContentReplacementState` 使用 `seenIds` 和 `replacements` 冻结每个 `tool_use_id` 的 fate。以前替换过的结果只做 Map lookup 重新应用同一段 replacement；以前没替换过的结果不能后来再替换，否则 provider cache 前缀会变。

`applyToolResultBudget(...)` 在 query 发包前执行，而不是工具刚返回时执行。这一点对 Holo 很关键：Holo 现在已经在 batch observation 层新增 replacement state，但它仍发生在 observation 构造阶段；还没有像外部项目那样在 provider 发包前对 API message 视图统一应用 replacement。

### Holo 当前已具备的控制流

Holo 的 deep loop 在 `kernel_v3/deep_loop.py:198-301` 中持续循环：compile context、propose assistant turn、执行工具或 terminal turn、evaluate、按 guard/stop 退出。这说明 Holo 已经有可持续 loop，不是单步 planner。

Holo 的多工具执行在 `kernel_v3/deep_loop.py:390-461`：先把 `turn.tool_calls` 转成 `CandidateAction`，走 manifest、policy、pre-exec guard，再通过 `StreamingToolExecutor.execute_batches(...)` 执行。这是正确骨架，但它的输入是完整 JSON assistant turn，而不是 provider streaming delta。

Holo 的工具上下文在 `kernel_v3/deep_loop.py:495-511` 绑定到 `_host_context` 后传给工具。`kernel_v3/tool_use.py:21-49` 的 `ToolUseContext` 目前已经包含 `runtime_spec`，但还没有 abort/progress、content replacement state 和显式 workbench state。

Holo 的工具执行事件在 `kernel_v3/tool_use.py:91-173`。但这里的 `StreamingToolExecutor` 当前是 batch/evented executor，注释也写明“future provider-streaming loop can feed items into the same executor”；所以它还不是外部项目那种 streaming executor。

Holo provider 当前仍在 `kernel_v3/processors/providers.py:183-193` 固定 `response_format=json_object` 且 `"stream": False`。这从根上限制了 deep loop：只能等完整 JSON 输出后再执行工具，无法在 tool_use delta 到达时启动工具。

### 2026-06-17 P0 接入后的当前状态

本次 P0 接入已经把几项“只在审查文档里”的合同落到了代码里，但还没有完成 provider-native streaming deep loop。

已经落地：

- `kernel_v3/contracts.py` 的 `ToolManifest` 有 `runtime` 默认字段，旧 manifest 反序列化时保持兼容。
- `kernel_v3/tool_runtime.py` 定义 `ToolRuntimeSpec`，并能从 manifest/action 投影 `concurrency_safe`、`read_only`、`open_world`、`interrupt_behavior`、`max_result_size_chars`、`should_defer`、`always_load` 等调度字段。
- `kernel_v3/tool_use.py` 的 `ToolUseContext` 已把 `runtime_spec` 注入工具执行上下文；`tool.discovery` 返回的 manifest summary 也暴露 runtime spec。
- `kernel_v3/deep_loop.py` 的 `_is_concurrency_safe(...)` 已改为读取 `ToolRuntimeSpec`，不再只靠 `input_schema["concurrency_safe"]`。
- `kernel_v3/tool_result_budget.py` 新增 `ToolResultReplacementState`，deep tool batch observation 会记录 `new_replacements` 和 `replacement_state`，并能从 journal observation reconstruct。
- `kernel_v3/processors/contracts.py` 新增 `ProcessorStreamEvent` / `StreamingProcessorProvider`，`kernel_v3/processors/fabric.py` 新增 `stream_events(...)`，`kernel_v3/processors/providers.py` 的 OpenAI-compatible provider 有 SSE parser 骨架。
- 新增结构测试覆盖 runtime spec 暴露、byte-stable replacement reapply、processor streaming dispatch/fallback。

仍未完成：

- `ProcessorFabric.stream_events(...)` 目前是事件收集接口，不是 deep loop 的主执行路径。
- `OpenAICompatibleProvider.stream(...)` 只能解析 OpenAI-style SSE chunks；尚未把 provider-native tool call delta 接到 Holo `ToolCall` / `CandidateAction` / policy / executor 链路。
- `DeepAgentLoopController` 仍以完整 JSON `assistant.turn` 为主，工具执行发生在模型完整返回之后；还没有“tool delta 一出现就启动工具”的 streaming loop。
- `ToolResultReplacementState` 当前替换的是 batch observation preview，尚未把完整大结果持久写入独立 tool-results 文件，也尚未做到外部项目那种 API message 发包前统一 `applyToolResultBudget(...)`。
- `interrupt_behavior` 已进入 runtime spec，但 running tool abort、child abort controller、subprocess/network signal 传递还没有闭合。
- deferred tool loading 仍是 manifest 搜索，不是 token-aware `should_defer` / `always_load` provider tool exposure。

### 对金融能力的直接影响

FinanceBench / FinQA 失败不应再按单题修补。当前缺口会系统性影响以下题型：

- 多 filing、多公司、多年份比较：缺少跨回合 result replacement 和 aggregate budget，长证据容易挤爆上下文。
- SEC/EDGAR 大 HTML/XBRL 证据：已有 artifact 化，但模型不能稳定地按需重读、替换和保持 cache 前缀。
- 表格推理 / FinQA program-like transforms：需要工具 discovery、calculator、table query、script exec、formula trace 在同一 workbench state 下可组合；当前 deep loop 暴露还不够厚。
- 长运行 live 题：缺少 progress、abort、timeout runtime spec，UbuntuHolo 稳定性风险仍高。
- 工具多而复杂的题：缺少 deferred tool loading，全部塞 prompt 成本高；不塞又可能让模型 one-shot 看不到工具。

### P0 剩余定义

P0 不是“再多注册几个金融工具”。P0 是把通用 agent loop 的执行合同打通：

1. `ToolRuntimeSpec` 全链路接入：manifest、discovery、tool context、executor concurrency、interrupt、result budget。
2. `ContentReplacementState` 全链路接入：batch result projection、artifact persistence、journal/transcript record、resume reconstruction。
3. `ProcessorProvider.stream(...)` 与 `ProcessorFabric.stream_events(...)`：先定义事件协议和 fake/provider tests，再接 OpenAI-compatible SSE。
4. streaming deep loop 双轨：支持 native streaming tool-use；保留 JSON `assistant.turn` fallback。
5. tool execution progress/abort：至少让长工具能发 progress observation，并让 interruptBehavior 真正生效。

只有这五点完成，Holo 才能说“理论上给足工具后可以解决 FB/FQA 所有类型题”。现在只能说已经有骨架，但关键工程不变量还没闭合。
