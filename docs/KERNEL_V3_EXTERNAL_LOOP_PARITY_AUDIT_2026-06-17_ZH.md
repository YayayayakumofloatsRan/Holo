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

Holo 已经从旧的一步一工具循环，升级到“provider-visible native tools + eager streaming tool execution + tool.discovery + artifact.read + ToolUseContext + artifact 化长结果 + provider-message replacement view + durable tool-result artifacts”的深循环骨架。

与外部成熟项目相比，Holo 已经超过约 95% 的 P0 架构阈值，但还没有完成 100% 的完整 streaming agent loop。当前 Holo 已经不再只是：

`完整 JSON assistant.turn -> 批量执行工具 -> observation 回流`

而是具备显式打开的中间形态：

`provider tool_call_delta -> 参数完整即启动工具 -> host 继续 drain provider stream -> completed observation / aggregate batch 回流`

外部项目的最终成熟路径仍然更强：

`provider streaming delta -> tool_use 块一出现就入队执行 -> progress/result 立即回流 -> 缺失/取消/失败 tool_result 全部补齐 -> 下一轮继续`

所以，Holo 现在的核心缺口不是再加某一道题的规则，而是把已经落地的流式工具骨架继续推进到“运行中 progress/result 可回注、进程/网络级 signal 传递、动态工具集预算优化、live debug50 证明”的工作台。

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

Holo 目前的 `kernel_v3/tool_use.py` 和 `kernel_v3/deep_loop.py` 已经实现 eager streaming execution：provider `tool_call_delta` 的 name/arguments 足够完整时，host 会立即走 policy/guard 并提交工具执行，同时继续 drain provider stream。它已经越过“completed assistant turn 后批处理”的阶段，并且 completed JSON-turn batch path 与 streaming path 都已有 runtime timeout/abort 边界；但还没有达到外部项目的完整 executor 语义：运行中 partial result 尚不能回注同一个 provider conversation，已运行子进程/网络请求的 signal 传递还没有完全闭合。

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

Holo 当前有 `ArtifactStore`、`content_projection`、`artifact.read`，并且金融开放组件已把长 SEC/document/table/market payload 写 blob。本次 P0 接入又新增了 batch observation 层的 `ToolResultReplacementState`、provider-message replacement view 和 durable `tool_result_full` artifact：`DeepAgentLoopController` 的 assistant prompt、`ProcessorFabric` 的 JSON prompt/request parameters、OpenAI-compatible `provider_messages` 与结构化 message content 会在 provider 发包前把已标记的长结果替换为稳定 bounded preview。完整工具结果会写入 artifact store，并通过 replacement `artifact_refs` 暴露给 `artifact.read`。它还没有达到外部项目的 100% 成熟度：resume/fork 后 provider-cache 字节级审计和运行中 partial result 回注仍需继续闭合。

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

- provider streaming tool-use 的运行中 partial result 回注。
- 已运行 subprocess/network 工具的进程/请求级 signal 传递。
- 厚工具合同的全链路执行语义。
- token-aware deferred tool loading 和动态 provider tool-set 扩展。
- resume/fork provider-cache 字节稳定审计。
- 类型化 live debug50 闭环结果。

所以，最诚实的状态是：

Holo 已经摆脱“一题一补丁”的最低级循环，单 agent 通用 loop 的架构成熟度已超过约 95%。下一次迭代不应该回到金融规则补丁，而应把本轮 P0 骨架继续向 100% 闭合：运行中 result/progress 回注、进程/网络级 signal 传递、动态工具集预算优化、以及 live debug50 的类型化证明。

## 建议实现顺序

1. 继续补齐 `ToolRuntimeSpec`，让 manifest 可表达的调度/预算字段真正支配 executor、interrupt 和 provider tool exposure。
2. 将剩余 `concurrency_safe` 兼容读法收口到 runtime spec，避免新工具继续把调度字段塞进 input schema。
3. 为 `ToolRegistry` 增加 async/progress 执行协议，旧同步 executor 自动包装。
4. 将当前 `ToolResultReplacementState` 升级为更完整的 `ContentReplacementState` 等价物，让 tool batch result projection、artifact persistence、journal reconstruction、provider 发包前 replacement 和 resume/fork cache 审计跨回合稳定。
5. 持续验证 provider-message replacement view 在 native message array、provider parameters 和 packet preview 的生产路径上不泄漏 raw result。
6. 扩展 OpenAI-compatible / DeepSeek provider 的 SSE streaming 生产路径和 tool-call delta normalization 的 live 验证。
7. 将 deep loop 的 eager streaming path 推进到运行中 progress/result 可回注，JSON assistant.turn 继续作为 fallback。
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

`src/services/tools/StreamingToolExecutor.ts:153-205` 为 sibling error、用户中断、streaming fallback 都生成 synthetic `tool_result`。这条不变量很重要：模型发出的每个 `tool_use` 必须最终对应一个成功、失败、取消或 fallback 的结果。Holo 现在已经把 completed JSON turn 和 eager streaming delta 都接到 observation / aggregate batch result，但 provider fallback、中断、非协作取消下的全量 synthetic result 配对还没有达到外部项目级别。

`src/services/tools/StreamingToolExecutor.ts:207-241` 根据 `interruptBehavior()` 决定用户新消息到来时工具是 cancel 还是 block。Holo 新增的 `ToolRuntimeSpec.interrupt_behavior` 已接到 cooperative timeout/abort 入口，但 child process、network request 和用户新消息打断语义仍需继续闭合。

### 外部项目的 tool result budget 不变量

`src/utils/toolResultStorage.ts` 定义的 `ContentReplacementState` 使用 `seenIds` 和 `replacements` 冻结每个 `tool_use_id` 的 fate。以前替换过的结果只做 Map lookup 重新应用同一段 replacement；以前没替换过的结果不能后来再替换，否则 provider cache 前缀会变。

`applyToolResultBudget(...)` 在 query 发包前执行，而不是工具刚返回时执行。这一点对 Holo 很关键：Holo 现在已经在 batch observation 层新增 replacement state，但它仍发生在 observation 构造阶段；还没有像外部项目那样在 provider 发包前对 API message 视图统一应用 replacement。

### Holo 当前已具备的控制流

Holo 的 deep loop 在 `kernel_v3/deep_loop.py:198-301` 中持续循环：compile context、propose assistant turn、执行工具或 terminal turn、evaluate、按 guard/stop 退出。这说明 Holo 已经有可持续 loop，不是单步 planner。

Holo 的多工具执行在 `kernel_v3/deep_loop.py` 中保留两条路径：JSON fallback 会把完整 `turn.tool_calls` 转成 `CandidateAction` 后批量执行；eager streaming path 会在 provider `tool_call_delta` 的 name/arguments 完整时立即走同一套 manifest、policy、pre-exec guard、network/tool budget 和 executor。剩余差距是运行中 partial result/progress 还不能回注同一个 provider conversation。

Holo 的工具上下文在 `kernel_v3/deep_loop.py` 绑定到 `_host_context` 后传给工具。`kernel_v3/tool_use.py` 的 `ToolUseContext` 目前已经包含 `runtime_spec`、progress channel、abort signal 和 timeout hints；content replacement 已在 provider JSON prompt view 落地，但显式 workbench state 与完整 `ContentReplacementState` 仍未闭合。

Holo 的工具执行事件在 `kernel_v3/tool_use.py`。这里的 `StreamingToolExecutor` 已经承担 queued / started / progress / completed / abort_requested 等 journal 事件，deep loop 的 eager streaming path 也能把 provider delta 喂入该执行层；但它还不是外部项目那种可把运行中结果持续 yield 回 provider conversation 的 executor。

初始审查时，Holo provider 固定 `response_format=json_object` 且 `"stream": False`，因此只能等完整 JSON 输出后再执行工具。后续 P0 已新增 provider-native tool surface、SSE parser 骨架、stream event contract 和 eager streaming execution；仍需扩大 OpenAI-compatible / DeepSeek 生产路径的 live 验证。

### 2026-06-17 P0 接入后的当前状态

本次 P0 接入已经把几项“只在审查文档里”的合同落到了代码里，但还没有完成外部项目级别的 provider-native streaming deep loop。

已经落地：

- `kernel_v3/contracts.py` 的 `ToolManifest` 有 `runtime` 默认字段，旧 manifest 反序列化时保持兼容。
- `kernel_v3/tool_runtime.py` 定义 `ToolRuntimeSpec`，并能从 manifest/action 投影 `concurrency_safe`、`read_only`、`open_world`、`interrupt_behavior`、`max_result_size_chars`、`should_defer`、`always_load` 等调度字段。
- `kernel_v3/tool_use.py` 的 `ToolUseContext` 已把 `runtime_spec` 注入工具执行上下文；`tool.discovery` 返回的 manifest summary 也暴露 runtime spec。
- `kernel_v3/deep_loop.py` 的 `_is_concurrency_safe(...)` 已改为读取 `ToolRuntimeSpec`，不再只靠 `input_schema["concurrency_safe"]`。
- `kernel_v3/tool_result_budget.py` 新增 `ToolResultReplacementState`，deep tool batch observation 会记录 `new_replacements` 和 `replacement_state`，并能从 journal observation reconstruct。
- `kernel_v3/processors/contracts.py` 新增 `ProcessorStreamEvent` / `StreamingProcessorProvider`，`kernel_v3/processors/fabric.py` 新增 `stream_events(...)`，`kernel_v3/processors/providers.py` 的 OpenAI-compatible provider 有 SSE parser 骨架。
- `kernel_v3/provider_tools.py` 新增 provider-native OpenAI-compatible tool surface：把 Holo `ToolManifest` 投影为合法 provider function name、JSON Schema 参数合同和 native-to-Holo name map。
- `ModelAssistantTurnPlanner(use_streaming=True)` 会把 native tools / name map 放入 processor request；`OpenAICompatibleProvider.build_payload(...)` 在 native tool 模式下发送 `tools` / `tool_choice`，并取消强制 `response_format=json_object`。
- stream-to-turn assembler 会把 provider 返回的 native function name 映射回 Holo 原始工具名，再进入 policy / executor。
- 新增结构测试覆盖 runtime spec 暴露、byte-stable replacement reapply、processor streaming dispatch/fallback、native tool surface schema、provider payload、native name 回映射执行。
- `ProcessorFabric.iter_stream_events(...)` 新增真正逐事件迭代接口；旧 `stream_events(...) -> list` 保持兼容并包裹新接口。结构测试证明消费第一个 event 时 provider 尚未被完整 drain，stream 结束后再写入完整 `processor_stream` journal。
- `DeepAgentLoopController` 新增 eager streaming execution path：`tool_call_delta` 的 name/arguments 足够完整时，立即复用 `_prepare_tool_call(...)` 走 action record、policy gate、pre-exec guard、network/tool-call budget，然后在线程池中提交工具执行，同时继续 drain provider stream。
- eager streaming path 会写入 `queued` / `started` / `completed` tool execution events，并在 stream drain 后写单项 observation 与 aggregate tool batch observation。结构测试证明 provider 在 `stream_end` 前能观察到工具已经启动。
- `ContextPackCompiler` 会把 tool batch result 中的 `content_replacement` 暴露到 recent observations 和 budget view，模型下一轮能看到稳定 replacement preview、artifact refs 和 `artifact.read` hint，而不是只看到 projection metadata。
- `ToolUseContext` 现在携带 `progress_channel_id`、`abort_signal_id` 和 `timeout_seconds`。协作式工具可通过 `emit_tool_progress(...)` 发 `progress` tool execution event，通过 `tool_abort_requested(...)` 响应 host abort signal。
- streaming futures 会读取 runtime `timeout_seconds`；超时后 host 记录 `abort_requested` 事件，设置 cooperative abort signal，并为不退出的工具生成 `tool_call_timeout` observation，避免 loop 无限等待。
- provider-native tool surface 已接入 runtime loading hints：`always_load` 工具优先进入 provider `tools`，`should_defer` 工具不直接进入 provider payload，而是进入 `native_tool_deferred` summary，供 `tool.discovery` 按需展开。
- `kernel_v3/tool_result_budget.py` 新增 `apply_provider_message_replacement_view(...)`；`DeepAgentLoopController` 的 `_assistant_turn_prompt(...)` 和 `ProcessorFabric` JSON request 构造都会在 provider 发包前应用 replacement view。结构测试证明原始大 preview 不会进入 prompt，模型只看到 bounded replacement preview。
- provider-message replacement view 已扩展到 `ProcessorFabric` request parameters、OpenAI-compatible `provider_messages`、结构化 message content、JSON 字符串 content 和 provider payload 返回前防线。
- `DeepAgentLoopController` 会把完整工具结果写入 `tool_result_full` artifact，并把 artifact id 回填进 batch result / replacement `artifact_refs`，模型可通过 `artifact.read` 按需读取。
- `ContextCompiler` wrapper 现在持有稳定 `ArtifactStore`；context budget view 会压缩普通 `tool_result` observation 的大字符串，并剔除 `_host_*` 执行上下文字段，避免 individual observation 绕过 batch projection 挤爆上下文。

仍未完成：

- `DeepAgentLoopController` 默认仍保留完整 JSON `assistant.turn` fallback；eager streaming path 需要 recipe metadata 显式打开 `agent_loop.provider_streaming=true` 或 `agent_loop.streaming=true`。
- eager streaming execution 已经做到“tool_call delta 完整即启动工具并继续 drain provider stream”，协作式工具运行进度也能进入 journal；但还没有把工具运行中的 partial result 反向注入同一个 provider conversation。
- `ToolResultReplacementState` 已能进入 batch observation、context pack、JSON provider prompt view、provider parameters / provider messages，并能用 `tool_result_full` artifact 保存完整工具结果；跨 resume/fork provider-cache 边界仍需完整 `ContentReplacementState` 等价审计。
- `interrupt_behavior` 已进入 runtime spec，协作式 abort signal 已能下发；但 child abort controller、subprocess/network signal 传递和非协作线程强中断还没有闭合。
- deferred tool loading 已进入 provider-native surface 的 `always_load` / `should_defer` 选择层；但还不是完整 token-budget 优化器，也没有按任务动态扩大 provider tool set。

### 2026-06-17 P0 续进：stream event 可进入 deep loop

本轮续进把 `ProcessorFabric.stream_events(...)` 从“只可单独测试的旁路”接到了 `ModelAssistantTurnPlanner`：

- `ModelAssistantTurnPlanner(use_streaming=True)` 会调用 `ProcessorFabric.stream_events(...)`，而不是 `run_json(...)`。
- 新增 stream-to-turn assembler，把 `content_delta`、`tool_call_delta`、`finish_delta`、`stream_end`、`stream_error` 组装成 Holo `AssistantTurn`。
- OpenAI-style `tool_call_delta` 支持按 `id` / `index` 合并分片，并把 `function.name` 和 `function.arguments` 规范化为 `ToolCallRequest`。
- malformed streamed tool arguments 不会静默丢失，会变成 `ToolCallParseError`，再由现有 deep loop 作为 `tool_call_parse_error` observation 回流。
- `AgentRuntime` 可通过 recipe metadata `agent_loop.provider_streaming=true` 或 `agent_loop.streaming=true` 显式打开 streaming planner；默认路径仍保留旧 JSON turn，避免破坏现有 live 路径。
- 结构测试已覆盖：streamed tool call delta 进入 `DeepAgentLoopController` 后执行 host policy/tool executor/journal；malformed streamed arguments 进入 parse error observation。

这一步是 P0 的必要中间层，但不是最终闭环。它证明 Holo 已经能消费 provider stream events 并进入深循环工具链；还没有做到外部项目那种“provider 流式输出 tool_use 的同时立即启动工具并并行 drain progress/result”。下一步必须把 execution 从 planner 返回后批量执行，推进到 provider stream 过程中即时入队执行。

### 2026-06-17 P0 续进：provider-native tool surface

本轮续进把“模型能不能在 provider 请求里真实看到工具”从 prompt 约定推进到了 provider payload 合同：

- `kernel_v3/provider_tools.py` 把 Holo `ToolManifest` 转成 OpenAI-compatible `tools` 数组；带点号的 Holo 工具名会被稳定映射为 provider 合法 function name，并保留 native-to-Holo name map。
- manifest `input_schema` 会保守投影为 JSON Schema：`str/int/number/bool/object/list[...]`、`required`、`min_length`、`min/max`、`description` 等已有字段被转写，`_runtime` 等 host-only 字段不会暴露成模型参数。
- `ModelAssistantTurnPlanner(use_streaming=True)` 现在在有 manifest 时携带 `native_tools`、`native_tool_name_map` 和 `tool_choice=auto`。
- `OpenAICompatibleProvider.build_payload(...)` 在 native tool 模式下发送 `tools` / `tool_choice`，并取消 `response_format=json_object`，避免 provider 同时被要求“只输出 JSON object”和“输出 tool call delta”。
- stream-to-turn assembler 解析到 native function name 后会映射回 Holo 原始工具名，再由现有 policy gate、schema canonicalization、executor、journal 处理。
- 结构测试覆盖 provider tool surface、OpenAI-compatible payload，以及 provider 返回 native name 后 deep loop 成功执行原始 Holo tool。
- `ProcessorFabric.iter_stream_events(...)` 提供逐事件消费入口，并在流结束后记录完整 processor stream journal；这一步是即时 tool execution 的必要前置。

这一步把成熟 agent loop 的“工具入口必须真实暴露给模型”和“provider stream 必须可被逐事件消费”补上了基础链路。

### 2026-06-17 P0 续进：eager streaming tool execution

本轮续进把 deep loop 从“stream 完成后再执行工具”推进到“stream 过程中启动工具”：

- `ModelAssistantTurnPlanner.stream_turn(...)` 返回 `AssistantTurnStream`，其中 `events` 是 `ProcessorFabric.iter_stream_events(...)` 的 iterable，而不是已收集完毕的 list。
- `DeepAgentLoopController` 会优先尝试 `_try_execute_streaming_turn(...)`；如果 planner 不支持 streaming，则回到旧 `propose_turn(...)` / JSON fallback。
- streaming path 逐个消费 provider event，持续合并 OpenAI-style `tool_call_delta`。当某个 tool call 的 name 存在且 arguments 已经能解析为 JSON object 时，立即构造 `ToolCallRequest`。
- 工具启动前仍复用 `_prepare_tool_call(...)`，所以 action journaling、policy decision、schema canonicalization、max tool calls、network budget、pre-exec guard 都没有被绕过。
- 工具执行通过线程池提交，host 继续 drain provider stream；完成后写入 `completed` tool execution event、单项 observation 和 aggregate tool batch observation。
- 结构测试 `test_streaming_planner_starts_tool_before_provider_stream_is_drained` 验证：provider 在 `stream_end` 前等待到工具线程启动，否则测试失败。
- malformed streamed arguments 仍会变成 parse error observation，而不是被即时路径吞掉。

这一步把成熟项目里最关键的 streaming tool-use 执行形态补到了 Holo 的 deep loop。它当时仍不是 95% 最终态；后续已经补上 cooperative progress/abort 和 provider-native deferred surface，但 tool-result replacement 还没有覆盖所有 provider message surface，金融 live debug50 也还没用这条路径证明。

### 2026-06-17 P0 续进：cooperative progress/abort 与 deferred provider tools

本轮续进补齐长工具可观测性和工具暴露预算的关键合同：

- `ToolUseContext` 新增 `progress_channel_id`、`abort_signal_id`、`timeout_seconds`，这些字段随 `_host_context` 进入工具执行 payload。
- `kernel_v3/tool_use.py` 新增 `emit_tool_progress(...)`、`tool_abort_requested(...)`、`tool_abort_reason(...)` 和 `tool_execution_control(...)`。旧同步工具不需要改；长工具可选择发 progress 或在 abort signal 置位时退出。
- `_execute_prepared_tool(...)` 在工具执行期间注册 progress channel 和 abort signal，所以无论工具来自 completed JSON turn 还是 streaming tool delta，都能用同一套 helper。
- streaming future 收集点按 runtime `timeout_seconds` 请求 cooperative abort；若工具不退出，host 返回 `tool_call_timeout` observation，并明确记录 Python thread 不能强杀的边界。
- 结构测试覆盖：progress helper、abort helper、deep loop progress journal、streaming timeout -> abort_requested -> failed tool batch result。
- `openai_native_tool_surface(...)` 现在读取 `ToolRuntimeSpec.always_load` / `should_defer`：always-load 工具优先暴露给 provider，deferred 工具进入 `native_tool_deferred` summary 而不是直接塞进 `tools` payload。

这一步把“长任务不黑盒卡住”和“工具太多时不把 provider payload 塞爆”的 P0 合同补上了工程入口。剩余不是普通接口问题，而是更硬的系统闭环：subprocess/network 的真实 signal 传递、所有 provider message surface 的统一 result replacement、以及 live debug50 证明。

### 2026-06-17 P0 续进：provider message replacement view

本轮续进补上了“大工具结果已经生成 replacement，但 provider prompt 仍可能带原始大 preview”的直接漏洞：

- `apply_provider_message_replacement_view(...)` 会递归扫描 provider-bound JSON payload；凡是带 `content_replacement` 的结果，都会把 `content_preview` 和 `content_projection.preview` 改写成 `replacement_preview`，并标记 `provider_message_replacement_applied=true`。
- replacement view 还会屏蔽带 replacement 的 result 中常见 raw 字段，如 `content`、`raw_content`、`full_output`、`raw_payload`，避免 provider message surface 因额外字段泄漏完整大结果。
- `_assistant_turn_prompt(...)` 在序列化 deep loop 上下文前应用该 view，避免 recent observations 中的原始大结果重新进入下一轮模型上下文。
- `ProcessorFabric._request(...)` 对包含 `content_replacement` 的 JSON prompt 和 request parameters 做同样处理，因此不只 deep loop helper，普通 JSON provider request 也有统一保险。
- `OpenAICompatibleProvider.build_payload(...)` 支持显式 `provider_messages`，并在 provider payload 返回前再做 replacement view；`packet_preview(...)` 对 structured message content 只显示 preview/hash/chars。
- 结构测试覆盖 helper、deep loop prompt、ProcessorFabric JSON prompt、ProcessorFabric parameters、OpenAI-compatible provider messages 五层，确认 `RAW-...` / `PROJECTED-...` / raw content 不进入最终 provider prompt。

这把成熟度从约 93%-94% 推进到约 95% 的 P0 架构阈值。它仍不是完整 `ContentReplacementState`：当前已覆盖 JSON prompt surface、provider parameters、structured provider messages 和 durable tool-result artifact，但 resume/fork 后 provider-cache 级字节稳定审计仍需继续补。

### 2026-06-17 P0 续进：durable tool-result artifacts 与 context budget 旁路收口

本轮续进还补上了“大结果虽然被 replacement，但完整结果没有稳定存储”以及“individual tool_result observation 绕过 batch projection”的缺口：

- `DeepAgentLoopController` 在生成 tool batch observation 时，为每个完整工具结果写入 `tool_result_full` artifact，payload 包含 task/run/step/turn/tool_call/action/observation envelope。
- batch result 会记录 `tool_result_artifact_id`，并把该 id 合并进 `artifact_refs`。当 replacement 被触发时，replacement 的 `artifact_refs` 也能指向这个完整工具结果 artifact。
- `ContextCompiler` wrapper 现在持有稳定 `ArtifactStore`，deep loop 写入的 artifact 能在后续 context / artifact.read 路径中继续存在。
- `ContextPackCompiler` 的 observation budget view 不再把普通 dict observation 的原始长字符串完整计入预算；它使用 compact content，并剔除 `_host_*` 内部执行上下文字段。
- 结构测试证明：60k 字符级工具结果会触发 replacement、完整结果可从 artifact store 读回、context pack 不再因为 individual tool_result 大字符串超预算。

### 2026-06-17 P0 续进：completed-turn batch timeout boundary

本轮续进补上了“streaming 工具有 timeout/abort，completed JSON turn batch 却可能卡在非协作工具”的缺口：

- `DeepAgentLoopController._execute_tool_turn(...)` 的 batch path 现在通过 `_execute_prepared_tool_with_timeout(...)` 执行工具，而不是直接同步调用 `_execute_prepared_tool(...)`。
- 当 `ToolRuntimeSpec.timeout_seconds` 存在时，host 会在独立 future 中执行工具；超时后设置 `ToolAbortSignal`、写入 `abort_requested` tool execution event，并给工具 0.25 秒 cooperative 收尾窗口。
- 若工具仍未返回，host 返回 `tool_call_timeout` observation，batch result 标记 failed，loop 继续推进，不再卡死在 completed-turn 工具执行阶段。
- streaming path 原有 timeout/abort 行为保持不变；现在 JSON fallback 和 streaming tool-use 两条路径有一致的 host timeout boundary。
- 结构测试覆盖非协作慢工具：工具不检查 abort signal，host 仍会返回 `tool_call_timeout`，并在 journal 中出现 `abort_requested`。

这把 P0 架构成熟度推进到 95% 以上。仍需注意：Python 线程本身不能被强杀；真正的 100% 方案要继续把 shell/script/browser/network 工具接到进程组、HTTP request、worker process 级 signal/timeout。

### 2026-06-17 P0 续进：复刻 StreamingToolExecutor 调度语义

本轮续进不是新增金融题规则，而是把外部 TypeScript 项目 `StreamingToolExecutor` 的核心调度合同移入 Holo eager streaming path：

- provider stream 中每次拿到完整 `tool_call_delta` 后，Holo 仍然立即走 `_prepare_tool_call(...)`，复用 manifest、policy、guard、network budget、tool budget 和 journal 路径。
- streaming path 不再简单把所有 ready tool future 提交给线程池；它维护 pending 队列并按 runtime `concurrency_safe` 判定启动时机。
- 当没有工具运行时，新工具可立即启动。
- 当新工具和所有运行中工具都显式 `concurrency_safe=true` 时，可以并行启动。
- 当任意运行中工具不是 concurrency-safe，或新工具自身不是 concurrency-safe 时，后续工具必须等待已有工具完成。
- 已完成工具会在继续 drain provider stream 的过程中被及时收割，写入单项 `tool_result` observation 和 `queued` / `started` / `completed` tool execution events。
- 结构测试覆盖了参考项目同款关键不变量：provider 连续吐出一个非并发安全写工具和一个并发安全读工具时，读工具必须等写工具 completed 后才 started。
- CLI 新增 `--agent-loop-streaming` / `--no-agent-loop-streaming`，会把 `agent_loop.provider_streaming` 写入 execution metadata；因此 live bench/chat/run 可以显式进入 provider streaming deep loop，不再只依赖内部 recipe metadata。
- live 单题探针暴露出 DeepSeek/OpenAI-style tool-call delta 的真实分片问题：第一片可能带 `id` / `index` / `function.name`，后续参数片只有 `index`。Holo 已修正为按 `index` 聚合同一 tool call，同时保留真实 `id` 作为 `tool_call_id`；没有收到非空 arguments 时不会把 `{}` 当作已完成参数执行工具。

这一步把 eager streaming execution 从“边 stream 边 submit future”推进到“边 stream 边按成熟 executor 语义调度”。它是通用 agent loop 能力，不是 FinanceBench 打表。

同时，finance final numeric preflight 增加了一个非评分性质的稳定性边界：最终 ledger 生成前的 model-first task.compile 可配置 1-120 秒 timeout，并且 final preflight 路径禁用 retry，避免 provider 卡顿导致已经完成 retrieval/tool/ledger 的 live run 在最后一步长时间挂住。这个边界不做语义判断，也不替代 LLM 解题；它只保证 loop 不被辅助编译请求拖死。

### 2026-06-17 P0 续进：finance document result budgeting

本轮 live streaming 单题探针证明 provider-native tool-call delta 已经能进入 Holo 的 policy/tool/journal 链路，但也暴露出真正的 P0 工具链问题：模型能调用 `document.docling.convert`，却可能只收到长 10-K/PDF 的开头截断文本，看不到远处的 capex、inventory、cash-flow 或资产负债表行。

这不是某一道 FinanceBench 题的规则补丁，而是成熟 agent loop 必须具备的工具结果预算能力：

- `_import_component(...)` 现在把 nested import probe 的 `ModuleNotFoundError` 等异常规范化为 `dependency_missing` observation，Docling 主进程缺依赖时能进入隔离 worker，而不是在 host 边界外抛异常。
- `document.docling.convert` 对 PDF URL 先走现有轻量 PDF extraction stack，再考虑 heavy Docling。这样 score-critical filing PDF 不会因为 full Docling worker 超时而直接失去证据。
- document conversion 返回 `focus_snippets`，并把这些高信号候选窗口放在 `text` 截断正文之前；默认覆盖 capex、PPE、operating cash flow、net sales/revenue、cost of sales、inventory、total assets、net income 等通用金融证据锚点，也允许模型通过 `focus_terms` 传入任务相关词。
- 隔离 Docling worker 也在完整导出文本上生成 `focus_snippets`，不再只把截断后的正文交给主进程补片段。
- 这些 snippets 只是候选证据窗口，不做事实绑定、公式选择、阈值判断或 benchmark answer 推断；语义判断仍由 LLM 完成，host 只治理工具结果的可见性、稳定性和 artifact 边界。

结构验证：

```bash
.venv/bin/python -m py_compile kernel_v3/finance/open_components.py tests/test_kernel_v3_finance_open_components.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_open_components.py -q
git diff --check
```

结果：`25 passed`。这是工具接口稳定性证据，不是 FinanceBench / FinQA accuracy。

### 与外部项目 agent loop 的剩余差距估计

这个估计只描述 agent loop 技术 parity，不是 FinanceBench / FinQA 分数。

按“复刻成熟项目的通用 agent loop”口径，当前已经超过约 95%。已经完成的是合同底座和显式入口：host-owned loop、tool manifest/runtime spec、tool discovery 暴露、tool context 注入、processor stream event、stream-to-turn assembler、parse error observation、provider-native tool surface、native-to-Holo tool name map、eager streaming tool execution、外部项目同款 concurrency-safe / exclusive streaming 调度、streaming 与 completed-turn batch timeout/abort boundary、deferred provider tool surface、JSON/provider-message replacement view、durable `tool_result_full` artifact、context budget 旁路收口、replacement context exposure、journal 记录。模型已经可以通过显式 streaming planner 在 provider 请求里看到 native tools，并把 provider stream event 带入 Holo 的 policy/tool/journal 链路。

距离外部项目 100% 成熟度还差的部分主要集中在剩余工程闭环：

- Tool result replacement 已覆盖 JSON provider prompt view、provider parameters、structured provider messages 和 durable artifact，但仍要做 resume/fork cache 稳定审计。
- Tool runtime spec 已驱动 cooperative progress/abort/timeout，并覆盖 streaming / completed-turn batch 两条路径；仍要接到 child process/network cancellation，解决已运行子进程/请求的真实中断。
- deferred/always-load 已进入 provider-native surface，但还需要按任务、token budget、tool.discovery 结果动态调整 provider tool set。
- Workbench state 仍要更明确地承载 SEC/EDGAR、table query、calculator、formula trace、artifact read、market/search 等临时组装能力。
- 类型簇 live debug50 仍未用新 streaming path 完成，结构成熟度不能替代 finance benchmark 证据。

按“能支撑 FB/FQA live debug 并显著刷分”的口径，当前约 60%-70%。原因是金融题不只需要 loop 会跑，还需要稳定证据读取、表格/公式/计算链、长结果预算、失败重规划和 live evaluation 闭环同时成立。结构进展不能替代 live 做题结果；下一阶段必须用类型簇 debug50 证明这些接口真的提升解题成功率。

### 对金融能力的直接影响

FinanceBench / FinQA 失败不应再按单题修补。当前缺口会系统性影响以下题型：

- 多 filing、多公司、多年份比较：provider-message replacement 与 durable tool-result artifact 已能控制长证据上下文压力；剩余风险是 resume/fork 后 cache 前缀稳定审计还不够强。
- SEC/EDGAR 大 HTML/XBRL 证据：已有 artifact 化、replacement view 和完整 tool result artifact；模型可以通过 artifact refs 按需重读，但 live debug50 还没证明每类 SEC 题都能稳定走通。
- 表格推理 / FinQA program-like transforms：需要工具 discovery、calculator、table query、script exec、formula trace 在同一 workbench state 下可组合；当前 deep loop 暴露还不够厚。
- 长运行 live 题：streaming 和 completed-turn batch 已有 timeout/abort boundary；剩余风险是 shell/script/browser/network 工具侧需要接入进程组或 request 级取消。
- 工具多而复杂的题：已有 provider-native deferred/always-load 选择层，但还缺动态 token-budget 工具集扩展。

### P0 剩余定义

P0 不是“再多注册几个金融工具”。P0 是把通用 agent loop 的执行合同打通：

1. `ToolRuntimeSpec` 全链路接入：manifest、discovery、tool context、executor concurrency、interrupt、result budget。
2. `ContentReplacementState` 全链路接入：batch result projection、provider prompt view、artifact/tool-results persistence 已有，下一步补 journal/transcript record 的 resume/fork 字节稳定审计。
3. `ProcessorProvider.stream(...)` 与 `ProcessorFabric.stream_events(...)`：事件协议和 fake/provider tests 已有，下一步要扩大 OpenAI-compatible / DeepSeek SSE live 证明。
4. streaming deep loop 双轨：native streaming tool-use 已有 eager path，下一步要支持运行中 progress/result 回注；JSON `assistant.turn` 继续作为 fallback。
5. tool execution progress/abort：cooperative helper 与 batch/streaming timeout boundary 已有，下一步要让 subprocess/network 工具真正接入进程组/request 级 signal 边界。

现在可以说单 agent loop 骨架已经超过约 95% 的 P0 架构阈值。只有这些剩余闭环和 live debug50 完成后，Holo 才能说“理论上给足工具后可以解决 FB/FQA 所有类型题”并把架构成熟度推进到外部项目级别。
