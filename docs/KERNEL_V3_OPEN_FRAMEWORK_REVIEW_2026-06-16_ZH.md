# Holo Kernel v3 开源框架审阅与吸收路线

日期：2026-06-16  
分支：`kernel-v3`  
目标：审阅 LangChain、LangGraph、Semantic Kernel / Microsoft Agent Framework、Hermes Function Calling、HERMES Math Agent，并结合 Kernel v3 近期开发文档，确定 Holo 接下来应当吸收什么、避免什么、如何落到工程路线。

配套落地实施文档：`docs/KERNEL_V3_FRAMEWORK_REFERENCE_IMPLEMENTATION_DOSSIER_2026-06-16_ZH.md`

---

## 0. 结论摘要

Holo Kernel v3 不应退化成某个框架的 wrapper。我们应该把它发展成一个 host-owned、LLM-driven、graph-native、可审计、可长期驻留的 agent kernel。

外部框架给出的共同方向是：

1. **LangChain** 证明了工具、模型、检索器、文档、向量库、回调等组件必须有统一接口和生态适配层。
2. **LangGraph** 证明了复杂 agent 不能只靠线性 prompt loop，必须有显式状态图、checkpoint、stream、interrupt、memory、replay 和可观测执行。
3. **Semantic Kernel / Microsoft Agent Framework** 证明了企业级 agent 需要 kernel/service/function/plugin/process/filter 的分层，以及多模型、多 agent、多工具协议的稳定抽象。
4. **Hermes Function Calling** 证明了工具调用协议必须显式、可校验、可递归：模型提出 tool call，host 验证 schema 并执行，再把 observation 交回模型。
5. **HERMES Math Agent** 证明了强能力不是靠 host 替模型思考，而是把 verifier 做成工具，让模型在关键步骤主动调用验证器，host 负责严格校验和记录。

结合 Kernel v3 已有工作，下一阶段最值得吸收的是：

- 把当前 agent loop 提升为 **typed state graph runtime**，而不是只在 journal 里回放线性事件。
- 把工具协议固化为 **ToolManifest -> ToolCall -> ToolResult / ToolError -> Observation**。
- 把金融、数学、物理、代码等能力做成 **domain pack**，每个 pack 只提供上下文、工具、验证器、prompt contract，不替模型做语义答案选择。
- 把 memory 从“被动 recall”升级为 **工作集 page-in、研究图谱、工具失败记忆、已验证结论记忆、反思巩固**。
- 把 benchmark 能力建设变成 **严格分集、live evidence、节点级成本/cache/失败原因统计**。
- 把 demo UI 从事件列表升级为 **真实 graph runtime 的可视化镜像**，节点状态、并行分支、工具调用、验证反馈、最终停止必须同步。

---

## 1. 审阅对象

本次审阅的参考仓库位于 `/tmp/holo_agent_framework_refs`：

| 框架 | 本地路径 | 参考价值 |
| --- | --- | --- |
| LangChain | `/tmp/holo_agent_framework_refs/langchain` | 组件接口、工具/模型/检索器生态、Runnable/Callback 思路 |
| LangGraph | `/tmp/holo_agent_framework_refs/langgraph` | 状态图、checkpoint、stream、interrupt、memory、replay、生产级 agent runtime |
| Semantic Kernel | `/tmp/holo_agent_framework_refs/semantic-kernel` | Kernel / plugin / function / process / filter / multi-agent 的企业级分层 |
| Hermes Function Calling | `/tmp/holo_agent_framework_refs/hermes-function-calling` | 显式工具调用格式、schema 校验、递归 observation loop |
| HERMES Math Agent | `/tmp/holo_agent_framework_refs/hermes-math-agent` | verifier-as-tool、单步验证、已验证结论记忆、数学能力工程化 |

同时复核的 Holo 内部文档包括：

- `docs/KERNEL_V3_PROJECT_STATUS_2026-06-14_ZH.md`
- `docs/KERNEL_V3_SYSTEM_REVIEW_2026-06-13_ZH.md`
- `docs/KERNEL_V3_AGENT_LOOP.md`
- `docs/HOLO_ARCHITECTURE_MAP.md`
- `docs/KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md`
- `docs/KERNEL_V3_FB_FAB_EXPERIMENT_SPLITS_2026-06-15.md`
- `docs/KERNEL_V3_FINANCE_ABILITY_METRICS_2026-06-15.md`
- `docs/KERNEL_V3_PROGRESS_2026-06-15_FINANCE_SLOT_BIND_CACHE.md`
- `AGENTS.md`

---

## 2. 外部框架可吸收部分

### 2.1 LangChain：组件生态与接口层

LangChain 最适合参考的是组件接口，而不是让 Holo 变成 LangChain app。

可吸收点：

1. **统一模型接口**：chat model、embedding model、reranker、structured output 都应该有统一调用层，避免 provider 细节污染 agent loop。
2. **工具抽象**：工具应该有 name、description、args schema、return schema、error contract、side effect 标注。
3. **文档与检索抽象**：Document、Retriever、VectorStore、Loader、Splitter 的接口值得借鉴。
4. **Runnable / Callback 思路**：处理器节点应能被组合、stream、trace、统计耗时与 token。
5. **生态适配层**：Holo 的长期价值不在重复造所有 connector，而在能稳定接入 SEC、EDGAR、Yahoo、FRED、新闻、数据库、shell、文件、浏览器、代码执行等工具。

对 Holo 的含义：

- `kernel_v3/processors` 和 `kernel_v3/tools` 应该有比现在更稳定的协议层。
- Finance pack 需要把 SEC facts、filing parser、calculator、numeric judge、citation validator 都注册成工具或 processor，而不是散落在 runtime 中。
- 通用能力来自可组合工具生态，不来自针对每类问题写规则分发。

不应照搬：

- 不应把 Holo 的核心 agent loop 放弃给 LangChain Agent。
- 不应用 callback 文本日志替代 Kernel v3 的 typed journal。

---

### 2.2 LangGraph：状态图运行时

LangGraph 是本次最值得吸收的对象。它的核心不是“画图”，而是把 agent 的运行变成显式的状态迁移。

可吸收点：

1. **StateGraph**：每个节点读写 typed state，边表示可恢复的执行关系。
2. **checkpoint**：长任务可以中断、恢复、replay，适合系统常驻 agent。
3. **stream**：UI 不应等任务结束后补画，而应该订阅 graph state delta。
4. **interrupt / human-in-the-loop**：遇到缺证据、歧义、权限、成本上限时，可以暂停给用户或上层 policy。
5. **memory/store**：线程状态、长期记忆、跨任务知识应该和 graph runtime 结合。
6. **并行分支**：检索、公式候选、事实候选、验证候选可以并行，再由模型或 verifier 合并。

对 Holo 的含义：

当前 Holo 已有 `LoopControllerV3`、`taskgraph`、journal、processors、retrieval workbench、finance domain pack，但真实执行仍偏“线性 loop + 后验 journal”。下一步应把执行对象显式变成：

```text
AgentState {
  user_request,
  thread_state,
  work_frame,
  context_packet,
  plan_state,
  tool_calls[],
  observations[],
  evidence_ledger,
  claim_ledger,
  verifier_results[],
  synthesis_state,
  memory_proposals[],
  cost_cache_metrics
}
```

并让每一步成为节点：

```text
UserEvent
  -> SemanticIntake
  -> TaskCompile
  -> ContextPageIn
  -> Planner
  -> ToolExecutor
  -> ObservationReducer
  -> EvidenceLedger
  -> DomainVerifier
  -> LLMRepairOrJudge
  -> Synthesizer
  -> FinalGate
  -> MemoryProposal
```

其中边不是关键词路由，而是 host 对 schema、权限、资源、验证状态、停止条件的控制；语义判断仍交给 LLM。

不应照搬：

- 不应把 graph 边写成金融题关键词规则。
- 不应让 host 用 graph edge 决定“哪个数字是答案”。
- 不应只为了 UI 画一个假图；graph 必须反映真实 runtime state。

---

### 2.3 Semantic Kernel / Microsoft Agent Framework：Kernel、插件和企业级分层

Semantic Kernel 的价值在于工程组织：Kernel 管服务，Plugin 管能力，Function 管可调用单元，Process 管长流程，Filter 管前后置治理。

可吸收点：

1. **Kernel 作为服务容器**：provider、memory、tool registry、policy、telemetry、journal 都应可注入。
2. **Plugin / Function**：金融、数学、物理、代码、研究、文件系统等能力应成为插件，不应混在一个 runtime 巨函数里。
3. **Process Framework**：长任务需要 process step、event、resume、branch、join。
4. **Filter / Middleware**：安全、成本、cache、schema validation、citation validation、output cleanup 应做成通用 middleware。
5. **多 agent / 多 provider**：未来可以支持 planner / researcher / verifier / synthesizer 不同模型，但共享同一个 host state。
6. **MCP / A2A 思路**：工具协议应为跨进程、跨服务、跨语言留出口。

对 Holo 的含义：

Kernel v3 应形成清晰层次：

```text
HoloKernel
  services: model providers, memory, retrieval, journal, telemetry
  plugins: finance, math, physics, code, browser, filesystem
  functions: tool manifests and processor nodes
  processes: long-running task graphs
  filters: policy, schema, provenance, cost, cache, verifier
```

这与 Holo 旧架构中的 Perception Bus、Memory Fabric、Action Market、Consciousness Ledger 并不冲突。Kernel v3 可以把旧的“主体性设想”落到更硬的工程抽象上：

- Perception Bus -> event intake / observation reducer
- Action Market -> tool registry / planner-proposed tool call
- Memory Fabric -> typed memory layers
- Consciousness Ledger -> journal + checkpoint + replay
- Processor Fabric -> graph nodes / plugins / process steps

不应照搬：

- 不应引入过重企业样板导致研发变慢。
- 不应把插件系统变成规则系统。插件只提供能力边界、工具、上下文、验证器。

---

### 2.4 Hermes Function Calling：显式工具调用协议

Hermes Function Calling 的核心是非常朴素但关键的工具闭环：

```text
model proposes tool_call
host parses and validates schema
host executes allowed function
host returns tool_response
model observes and continues or finalizes
```

可吸收点：

1. **工具调用必须结构化**：不能依赖文本里猜“模型想调用什么”。
2. **host 只验证和执行**：host 不替模型做语义决策。
3. **递归 observation loop**：一次工具返回后，模型可以继续请求下一步。
4. **max depth / stop condition**：防止简单任务陷入无限 loop。
5. **错误也要成为 observation**：schema 错误、权限错误、检索失败、解析失败都应反馈给模型。

对 Holo 的含义：

Kernel v3 已经在这条路上，但还需要进一步统一：

```text
ToolManifest {
  name,
  description,
  args_schema,
  result_schema,
  side_effects,
  cost_class,
  cache_policy,
  provenance_policy
}

ToolCall {
  call_id,
  tool_name,
  arguments,
  requested_by_node,
  model_message_id
}

ToolResult {
  call_id,
  status,
  observation,
  citations,
  artifacts,
  cost,
  cache_hit,
  error
}
```

这会同时改善：

- 金融做题能力：事实、公式、检索、验证每一步都更清楚。
- 通用能力：临时组装工具链更自然。
- UI：graph 节点可以显示真实 ToolCall / ToolResult，而不是事后拼文字。
- 成本：每个工具和 processor 的 cache hit 可以统计。

不应照搬：

- 不应暴露 provider 私有 chain-of-thought 作为产品依赖。应暴露模型显式输出的计划、工具调用、观察、验证反馈、公开推理摘要和状态变化。
- 不应让 tool template 成为固定答案模板。

---

### 2.5 HERMES Math Agent：Verifier-as-Tool

HERMES Math Agent 最关键的启发是：强 reasoning system 不需要 host 代替模型推理，而是让模型在关键声明处调用验证器。

可吸收点：

1. **单步验证**：不要只在最终答案才验证，应对关键 claim / calculation / transformation 做局部验证。
2. **verifier 是工具**：模型决定何时需要验证，host 提供可靠验证环境。
3. **验证结果进入 memory**：已验证的中间结论可以复用，避免重复推理。
4. **失败反馈回模型**：`INCORRECT` 或 `VERIFICATION FAILURE` 应触发模型修复，而不是 host 自己改答案。
5. **领域可替换**：数学用 Lean，金融用 fact ledger + formula trace + numeric judge + citation validator，代码用 tests/typecheck/lint。

对 Holo 的含义：

金融 agent 的 verifier 不应只是最终打分器，而应拆成：

```text
ClaimVerifier
  - 事实是否有来源
  - 数值是否来自 evidence / formula trace
  - 单位是否一致
  - 期间是否由模型 slot binding 明确选择
  - 引用是否覆盖关键结论

CalculationVerifier
  - 公式依赖是否齐全
  - 计算是否可复现
  - 结果单位和格式是否一致

AnswerCleanlinessVerifier
  - 最终答案是否加入了无来源阈值、行业倍数、装饰性数字
  - 是否把 supported trace 外的数字写入结论
```

这与近期 `finance.slot_bind`、formula trace、numeric judge、repair synthesis 的方向一致。下一步应让这些 verifier 更像工具，而不是嵌在 host fallback 中。

不应照搬：

- 不应把 verifier 变成答案生成器。
- 不应让 verifier 用 gold/reference 参与运行时。
- 不应对金融 benchmark 做表驱动判断。

---

## 3. Holo 已经做对了什么

从近期开发文档看，Kernel v3 已经具备一个严肃 agent harness 的雏形：

1. **Host-owned harness**：模型提出，host 验证、执行、记录、校验、停止。
2. **完整 agent loop**：semantic intake、task compile、planner、tool execution、retrieval、claim/slot/transform/verifier/synthesis gate、journal。
3. **金融 domain pack 雏形**：finance fact ledger、slot binding、formula trace、numeric judge、citation validation、synthesis rescue。
4. **benchmark 纪律**：FB debug / holdout 分离，FAB 另算，gold/reference 只用于 post-run scoring。
5. **live evidence**：已有 FinAgent full40 strict live 38/40，rescored 39/40；FinanceBench doc retrieval 更难，目前中等表现。
6. **memory 方向明确**：journal、working memory、durable memory、retrieval graph、workmethod、mission supervisor 都已有入口。
7. **demo UI 已可展示**：Windows 浏览器端可观察 thread、chat、agent topology、console/event。
8. **prompt/cache 意识已建立**：稳定 contract/schema 前缀、动态事实后置、processor 级缓存指标已被列入路线。

因此，Holo 不是“从零开始”。真正的问题是：已有部件还没有被收束成一个清晰、稳定、可复用、可观测、可评测的 graph runtime。

---

## 4. 当前最关键短板

### 4.1 Agent loop 仍不够 graph-native

UI 上看到的 topology 和 runtime state 仍有脱节风险。真正需要的是 graph state 驱动 UI，而不是 UI 自己根据 journal 猜图。

影响：

- answer complete 后事件还在跳动，会让人怀疑停止条件不清楚。
- tool/search/answer 亮灯顺序不稳定，会让演示显得不可信。
- 并行分支、重试、repair、verifier 没有被直观表达。

改进方向：

- graph node 状态必须来自同一个 authoritative runtime state。
- 每个 turn 完成时写入 terminal state，之后不能再改变本 turn 的 topology。
- UI 订阅 state delta，不事后补画。

### 4.2 金融能力强点明显，但泛化仍受 slot / synthesis 影响

Holo 对明确财务报表数值、公式型问题、source-grounded metric retrieval 已经有能力基础。但难题中的瓶颈是：

- noisy companyfacts 下期间选择和 line item disambiguation。
- 多来源、多单位、多期间的 slot binding。
- 合成器在已有正确 formula trace 后加入无来源数字。
- 最终 verifier / repair loop 消耗偏大。

改进方向：

- LLM-owned slot binding 更强，上下文更长但更稳定。
- Finance fact ledger 按 source/profile/period/unit/provenance 结构化。
- 单步 claim/calculation/answer cleanliness verifier 工具化。
- 合成器只能消费 allowed facts / formula traces / citations。

### 4.3 Memory 仍偏被动

已有 memory/retrieval 设计，但还没有充分进入 planner 的工作习惯。

缺口：

- 没有稳定的 task-start memory page-in。
- 没有把“上次某类题失败原因”主动交给 planner。
- 没有 verified-claim memory。
- 没有 tool failure memory，例如某 SEC fact key 在某公司经常不可靠。

改进方向：

- 每个 task compile 后产生 `MemoryIntent`。
- planner 可以调用 `memory.recall`，但 host 也可提供 compact working set。
- 完成任务后产生 memory proposal，经过过滤后固化。

### 4.4 成本/cache 还不是一等指标

用户已经明确：cache hit 比 token 总量更关键，因为命中缓存后的成本和延迟显著下降。

改进方向：

- 每个 processor 记录 prompt prefix hash、dynamic suffix hash、cache hit/miss、token、latency、provider。
- 稳定系统 contract、tool schema、domain instructions 前置。
- benchmark report 必须包含 cache hit rate。
- 对高频节点做 prompt packet freeze，避免每题重新扰动前缀。

### 4.5 通用能力需要统一底座，而非金融特例

Kernel v3 的目标是常驻智能工作基座，金融只是当前重点 profile。若金融能力靠特殊规则堆出来，会牺牲通用能力。

改进方向：

- 通用 loop：observe -> plan -> tool -> observe -> verify -> synthesize -> remember。
- domain pack 只改变工具、上下文、验证器、prompt contract。
- 数学/物理/代码/研究任务也走同一个 graph runtime。

---

## 5. Holo 应采用的 Kernel v3.1 结构

### 5.1 Runtime 分层

```text
HoloKernel
  ModelRuntime
    - provider adapters
    - structured output
    - token/cache accounting

  AgentGraphRuntime
    - typed state
    - node execution
    - branch/join
    - checkpoint/replay
    - stream delta
    - stop controller

  ToolRuntime
    - ToolManifest registry
    - schema validation
    - permission/policy gate
    - ToolCall execution
    - ToolResult normalization

  MemoryRuntime
    - event memory
    - thread working set
    - durable memory
    - research graph
    - verified-claim memory
    - tool failure memory

  DomainPacks
    - finance
    - math
    - physics
    - code/workspace
    - research/web

  ObservabilityRuntime
    - journal
    - graph state stream
    - node metrics
    - benchmark reports
    - UI API
```

### 5.2 Canonical agent graph

```text
[User/Event]
    |
    v
[Semantic Intake]
    |
    v
[Task Compile]
    |
    v
[Context Page-In] <---- [Memory Recall]
    |
    v
[Planner]
    |
    +--> [Tool Branch A: Retrieval]
    |
    +--> [Tool Branch B: Calculator]
    |
    +--> [Tool Branch C: Filing Parser]
    |
    v
[Observation Reducer]
    |
    v
[Evidence / Claim Ledger]
    |
    v
[Verifier Tools]
    |
    +--> pass ----> [Synthesizer]
    |
    +--> fail ----> [LLM Repair / Replan] -> [Planner]
    |
    v
[Final Gate]
    |
    v
[Answer + Memory Proposal + Metrics]
```

这张图的关键是：Planner、slot binding、claim selection、final synthesis 都由 LLM 完成；host 执行工具、验证 schema、控制权限、记录状态、进行可复现计算和事实一致性校验。

### 5.3 Domain pack 标准

每个 domain pack 应提供：

```text
DomainPack {
  name,
  system_contract,
  tool_manifests[],
  context_compilers[],
  verifier_tools[],
  memory_profiles[],
  benchmark_profiles[],
  ui_render_hints[]
}
```

Finance pack：

- SEC / filings / companyfacts / market data / calculator / citation 工具。
- LLM-owned fact-to-slot binding。
- FormulaTrace 和 NumericJudge。
- AnswerCleanlinessVerifier 防止无来源数字。
- FB/FAB/FinAgent/Holo workflow challenge benchmark profiles。

Math pack：

- symbolic algebra、numeric check、formal verifier、proof step validator。
- verified theorem/lemma memory。

Physics pack：

- unit/dimensional analysis、equation solver、simulation/numeric check。
- assumption ledger。

Code/workspace pack：

- file read/write、shell、test、lint、git、package manager、browser。
- patch verifier、test result memory。

---

## 6. 对金融能力的直接提升路线

### 6.1 不再扩大 host 语义规则

禁止项：

- host 用关键词/阈值决定哪个数字是答案。
- host 用规则判断哪个 row 是模型想要的 metric。
- host 不经过 LLM slot binding 自己选事实、套公式、生成答案。
- benchmark gold/reference 进入运行时 prompt、memory、retrieval 或工具。

允许项：

- host 校验 schema。
- host 校验 fact id 是否存在。
- host 做模型指定公式的可复现计算。
- host 检查最终答案数字是否来自 evidence/formula trace/citation。
- host 把 verifier failure 反馈给模型请求修复。

### 6.2 Finance answer path

推荐标准路径：

```text
Question
  -> LLM task compile
  -> Retrieval / filing evidence
  -> Finance fact ledger
  -> LLM slot_bind
  -> Host calculator executes selected formula
  -> FormulaTrace
  -> Claim / numeric verifier
  -> LLM synthesis
  -> AnswerCleanlinessVerifier
  -> final
```

这条路径可以解释给评审：Holo 不是硬编码金融题，而是用工具和验证器驯服模型，让模型在可审计环境里完成专家级判断。

### 6.3 近期最值得做的金融增强

1. **Fact ledger profile**：把 SEC companyfacts、10-K/10-Q table、press release、market data 分 profile，标注可信边界。
2. **Slot binding prompt v2**：一次性给足 line item、period、unit、source、formula dependency，让模型输出 slots + confidence + rejected alternatives。
3. **Formula hypothesis parallelism**：同一题可让模型提出多个可行 formula plan，host 并行计算，再让模型选择最符合题意的 trace。
4. **Answer cleanliness loop**：最终答案只能包含 supported values；无来源阈值和装饰数字直接要求模型重写。
5. **Finance memory**：记录每类失败：period mismatch、unit mismatch、wrong company, wrong metric, unsupported comparison number。
6. **Large live eval**：FB debug/holdout 分离，FAB 单独跑，记录 pass/numeric/workflow/substrate/cache/latency。

---

## 7. 对通用能力的直接提升路线

Kernel v3 的通用能力应来自统一的 graph runtime，不是金融分支里的特殊逻辑。

通用任务形态：

```text
observe user event
infer task type and risk
load relevant memory/context
plan tool sequence
execute tools
reduce observations
verify claims / artifacts
answer or ask clarification
write memory proposal
stop cleanly
```

覆盖任务：

- 普通问答：少工具、低成本、快速停止。
- 文件/代码任务：读文件、改 patch、跑 test、总结。
- 研究任务：检索、来源评价、证据合成。
- 数学/物理：符号/数值/单位/形式化 verifier。
- 金融：财报检索、指标计算、事件分析、估值、风险、对比研究。
- role play / companion：使用长期记忆和风格 profile，但不污染严肃工作模式。

关键是 stop controller：

- 简单问候不应进入深 retrieval loop。
- 高风险金融/法律/医疗/投资问题应自动提高 evidence requirement。
- 用户明确要求 live/current 时才触发外部检索。
- 没有足够证据时，应说明缺口或请求工具权限，而不是无限循环。

这里的判断仍应主要由 LLM 给出 task/risk/evidence_need，host 只做预算、权限、loop limit、schema 和状态控制。

---

## 8. UI / Demo 应如何向框架学习

UI 不是独立表演层，它应该是 graph runtime 的镜像。

应展示：

1. **Chat 主界面**：用户输入、模型最终回复、可复制 artifact。
2. **Graph topology**：节点、边、分支、join、当前 active node、terminal state。
3. **Tool calls**：工具名、入参摘要、耗时、状态、cache hit、关键 observation。
4. **Verifier feedback**：哪些 claim 通过，哪些被打回，如何进入 repair。
5. **Memory panel**：本轮 page-in 了什么，提出了什么 memory proposal。
6. **Cost/cache metrics**：token、latency、cache hit、provider、processor。
7. **Benchmark panel**：题目、数据集、debug/holdout 标记、pass/numeric/workflow、失败原因。

不应展示：

- 假 topology。
- 事后乱跳的 graph。
- 与 runtime 不一致的 execution signal。
- 过多原始日志。
- provider 私有 chain-of-thought。应展示公开结构化 trace：计划、工具、观察、验证、修复、停止原因。

Graph 节点状态建议：

```text
idle
queued
running
waiting_tool
waiting_model
verifying
repairing
completed
failed
skipped
```

每个 turn 一旦 final gate completed，就冻结本 turn graph。后续 memory consolidation 或 telemetry 应作为 background task 单独显示，不应改变已完成 turn 的 graph。

---

## 9. Benchmark 与论文证据协议

论文和报告需要的不只是高分，还需要可信分。

必须记录：

```text
dataset
split
item_count
pass_rate
numeric_accuracy
workflow_score
substrate_score
citation_coverage
formula_trace_coverage
repair_rate
avg_model_calls
avg_tool_calls
avg_tokens
cache_hit_rate
avg_latency
failure_taxonomy
run_id
commit_sha
provider/model
```

分集规则：

- FB debug：只用于系统调试，当前约定 offsets 0-9。
- FB holdout：能力报告，当前约定 offsets 10-149。
- FAB：另算，不与 FB 混合。
- FinAgent：另算，适合展示多跳金融 agent 能力。
- Holo workflow challenge：内部综合题，必须标注为 internal challenge。

评分原则：

- gold/reference 只能用于 post-run scoring。
- 运行时不得读取 gold。
- 人工复核可以判断“答案合理”，但必须保留原始 output、evidence、review note。
- 不能用打表、关键词拦截、阈值模板骗过 benchmark。

论文叙事：

> Holo Kernel v3 uses an LLM-owned semantic loop inside a host-owned verifiable harness. The host does not select answers by benchmark-specific rules; it validates schemas, executes tools, records evidence, verifies claims, and asks the model to repair unsupported outputs.

---

## 10. 近期工程落地顺序

### P0：把当前工作收束为可信基线

1. 固化 `ToolManifest / ToolCall / ToolResult` schema。
2. 固化 `AgentState` 和 graph node 状态枚举。
3. 让 UI 直接订阅 graph state delta。
4. 确保 final 后本 turn graph 不再变化。
5. benchmark runner 输出统一 metrics。

### P1：金融能力强攻

1. Finance fact ledger v2：source/profile/period/unit/provenance 标准化。
2. Slot binding prompt v2：模型输出 selected slots、rejected alternatives、confidence、needed tools。
3. FormulaTrace v2：支持链式公式、并行候选、单位检查。
4. AnswerCleanlinessVerifier：清除无来源数字。
5. Debug set 快速迭代，holdout 大规模 live 测。

### P2：并行 agent loop

1. 检索并行：SEC facts、filing text、web/search、local cache 同时跑。
2. 公式候选并行：不同 ratio/metric hypothesis 同时计算。
3. verifier 并行：citation、numeric、unit、answer cleanliness 同时检查。
4. merge 由 LLM 或 adjudicator node 完成，host 只保证输入来源清楚。

### P3：Memory / cache

1. Processor prompt prefix freeze。
2. 每节点 cache metrics。
3. Thread working set page-in。
4. Verified claim memory。
5. Tool failure memory。
6. Reflection consolidation 后台化。

### P4：通用能力

1. 低风险 quick chat path。
2. 文件/代码任务 path。
3. research path。
4. math/physics verifier path。
5. role/memory mode 与严肃工作 mode 分离。

---

## 11. 可用于讲稿的表述

### 11.1 Holo 与 LangChain/LangGraph 的关系

Holo 不是对 LangChain 或 LangGraph 的简单包装。LangChain 代表工具生态和组件接口，LangGraph 代表状态图和持久化 agent runtime。Holo 要吸收这些思想，但保持自己的核心定位：host-owned harness，LLM-owned semantic decision，domain-verifiable intelligence。

### 11.2 Holo 与 Semantic Kernel 的关系

Semantic Kernel 给出了企业级 agent 的工程分层：kernel、plugin、function、process、filter。Holo 应把金融、数学、代码、研究能力做成 domain packs，让它们共享同一套 agent graph、memory、tool、verification 和 observability runtime。

### 11.3 Holo 与 Hermes 的关系

Hermes Function Calling 说明工具调用必须结构化、可验证、可递归。HERMES Math Agent 说明 verifier 应作为工具嵌入推理过程。Holo 的金融 agent 也应如此：模型决定 slot、事实、公式、结论；host 执行工具、计算 trace、验证 claim，再把错误反馈给模型修复。

### 11.4 Holo 的论文核心

Holo Kernel v3 的核心贡献不是某个金融指标计算器，而是一种可迁移的 agent harness：模型负责语义推理，host 负责工具执行、证据组织、验证、记忆和可观测性。在金融任务上，这个 harness 表现为 source-grounded financial investigation；在数学和物理任务上，它表现为 verifier-assisted reasoning；在代码和研究任务上，它表现为可审计的数字工作流。

---

## 12. 最终建议

下一阶段不要再横向增加零散功能，而应集中做三件事：

1. **Graph-native runtime**：把 agent loop 的真实状态图做出来，并让 UI、journal、benchmark 都消费同一个 state。
2. **Finance verifier + slot binding 强化**：继续保持 LLM 主导，把 host 的作用限制在结构校验、工具执行、可复现计算、证据一致性验证。
3. **Memory/cache/metrics 一体化**：让系统能长期工作、能复用上下文、能降低成本、能用统计结果证明能力提升。

如果这三件事落地，Holo Kernel v3 就能从“可以演示的金融 agent”升级为“有论文支撑、可持续迭代、可迁移到通用智能工作的 agent kernel”。
