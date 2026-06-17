# Holo Kernel v3 开源框架审阅与开发过程总成文档

日期：2026-06-16  
分支：`kernel-v3`  
用途：结项报告、讲稿、论文方法章节、Kernel v3.1 迭代路线  

---

## 0. 结论

审阅 LangChain、LangGraph、Semantic Kernel / Microsoft Agent Framework、
Hermes Function Calling、HERMES Math Agent，并回看 Kernel v3 最近一路开发文档后，
可以形成一个稳定判断：

**Holo 不应该成为任何现成框架的 wrapper。Holo 应该吸收这些框架已经验证过的工程原则，继续落成一个 host-owned、LLM-driven、tool-coupled、memory-aware、graph-observable 的通用 agent kernel。**

金融仍是当前最重要的压力测试场景，因为金融题同时考验检索、证据、表格、口径、单位、公式、引用、验证、成本和最终合成。但金融能力不能写成金融规则脚本。正确路线是：

```text
Generic AgentGraph Runtime
  + Standard Tool Protocol
  + Processor / Provider Fabric
  + Durable Memory / Working Set / Research Graph
  + Domain Packs
  + Verifier-as-tool
  + Benchmark / Telemetry / UI
```

其中 finance pack 是第一个高压 domain pack。未来数学、物理、代码、研究、文件工作、role play 和系统常驻任务，都应该共享同一套 agent loop。

Kernel v3 的硬不变量继续保持：

- LLM 负责语义判断、计划、slot binding、证据取舍、答案合成。
- Host 负责 schema、权限、工具执行、日志、验证、成本、cache、memory 和停止边界。
- Gold/reference 只用于 post-run scoring，不能进入 runtime prompt、memory、retrieval context 或 tool context。
- 禁止答案表、关键词拦截、阈值捷径、host 代替模型选择金融事实或最终数字。

---

## 1. 审阅材料

### 1.1 外部框架

| 框架 | 官方资料 | 对 Holo 的核心参考 |
| --- | --- | --- |
| LangChain | <https://docs.langchain.com/oss/python/langchain/overview>, <https://docs.langchain.com/oss/python/langchain/agents> | model、tools、prompt、middleware、structured output、provider abstraction、observability |
| LangGraph | <https://docs.langchain.com/oss/python/langgraph/overview>, <https://docs.langchain.com/oss/python/langgraph/persistence> | state graph、long-running agents、checkpoint、streaming、interrupt、memory、replay |
| Semantic Kernel | <https://learn.microsoft.com/en-us/semantic-kernel/overview/>, <https://learn.microsoft.com/en-us/semantic-kernel/concepts/plugins/>, <https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/filters> | kernel、service、plugin、function、process、filter、enterprise governance |
| Hermes Function Calling | <https://github.com/NousResearch/Hermes-Function-Calling> | schema tool-call loop、tool response、JSON mode、recursive tool use |
| HERMES Math Agent | <https://github.com/aziksh-ospanov/HERMES> | verifier-as-tool、formal verifier、verified-claim memory、agent/verifier coupling |

本地此前已把参考仓库放在 `/tmp/holo_agent_framework_refs`，并形成了配套文档：

- `docs/KERNEL_V3_OPEN_FRAMEWORK_REVIEW_2026-06-16_ZH.md`
- `docs/KERNEL_V3_FRAMEWORK_REFERENCE_IMPLEMENTATION_DOSSIER_2026-06-16_ZH.md`
- `docs/KERNEL_V3_FRAMEWORK_SYNTHESIS_AND_NEXT_ACTIONS_2026-06-16_ZH.md`
- `docs/KERNEL_V3_FRAMEWORK_REVIEW_AND_HOLO_ROADMAP_2026-06-16_ZH.md`
- `docs/KERNEL_V3_FRAMEWORK_REFERENCE_BRIEF_2026-06-16_ZH.md`

### 1.2 Holo 内部开发文档

本次重点复核：

- `docs/KERNEL_V3_AGENT_LOOP.md`
- `docs/KERNEL_V3_PROJECT_STATUS_2026-06-14_ZH.md`
- `docs/KERNEL_V3_SYSTEM_REVIEW_2026-06-13_ZH.md`
- `docs/KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md`
- `docs/KERNEL_V3_FINANCE_ABILITY_METRICS_2026-06-15.md`
- `docs/KERNEL_V3_FB_FAB_EXPERIMENT_SPLITS_2026-06-15.md`
- `docs/KERNEL_V3_PROGRESS_2026-06-15_FINANCE_SLOT_BIND_CACHE.md`
- `docs/KERNEL_V3_PROGRESS_2026-06-16_PROCESSOR_USAGE_CACHE_METRICS.md`
- `docs/PROCESSOR_ROUTING_AND_COST_POLICY.md`
- `docs/HOLO_ARCHITECTURE_MAP.md`
- `AGENTS.md`

这些文档共同说明：Holo 的开发不是随机堆叠功能，而是从对话系统、记忆系统、工具系统、检索系统、金融基准和可视化系统逐步收敛到 host-owned agent harness。

---

## 2. 外部框架可以参考什么

### 2.1 LangChain：参考接口生态，不接管核心 loop

LangChain 的重要经验是：一个 agent harness 的基本构件应当非常清楚。

对 Holo 可吸收：

- 标准 model / processor 接口，避免 provider 细节污染 agent loop。
- 标准 tool 接口，包含 name、description、args schema、return schema、side effect、cost、timeout、error contract。
- retriever、document、loader、splitter、vector store 的边界。
- structured output、middleware、observability、usage tracing。
- 第三方 connector 的适配方式。

落到 Holo：

- `kernel_v3/processors` 继续作为 provider-agnostic processor fabric。
- `kernel_v3/tools.py` 和 domain pack 工具应稳定成统一协议。
- `kernel_v3/retrieval` 应继续拆分 provider、loader、extractor、ranker、evidence reducer。
- finance、math、physics、code、workspace、browser 应成为 domain/tool pack，而不是散落在 runtime 巨函数里。

不应照搬：

- 不用 LangChain Agent 替代 Holo 的 host-owned loop。
- 不用文本 callback 替代 typed journal。
- 不为了生态便利牺牲安全边界、审计能力和 benchmark 防泄漏。

### 2.2 LangGraph：下一阶段最重要的 runtime 参考

LangGraph 的核心不是“画图”，而是让 agent 成为显式、可恢复、可流式观察的状态机。对 Kernel v3 来说，这是下一步最重要的架构参考。

Holo 应吸收：

- StateGraph：每个节点读写 typed state。
- Checkpoint / resume / replay：长任务、常驻任务、夜间 benchmark 和中断恢复都需要。
- Streaming state delta：CLI、dashboard、benchmark report 订阅同一套 runtime delta。
- Interrupt / human-in-the-loop：证据不足、权限、成本、用户确认时能暂停。
- Branch / join：检索、候选事实、候选公式、反证、验证器可以并行。
- Memory/store：thread working set 和 durable memory 是 state 的组成部分。

建议 Holo 定义：

```text
AgentGraphState {
  user_request,
  thread_context,
  work_frame,
  domain_profile,
  tool_manifest,
  plan_state,
  active_branches,
  observations,
  evidence_ledger,
  claim_ledger,
  formula_traces,
  verifier_results,
  synthesis_state,
  memory_proposals,
  cost_cache_metrics,
  stop_state
}
```

标准节点：

```text
UserEvent
SemanticIntake
TaskCompile
ContextPageIn
Planner
ToolExecutor
ObservationReducer
EvidenceLedger
DomainVerifier
RepairOrReplan
Synthesizer
FinalGate
MemoryProposal
StopController
```

禁止事项：

- 不用 graph edge 写金融关键词规则。
- 不让 host edge 条件决定哪个金融数字是最终答案。
- 不为了 demo 画假 topology。UI 只能渲染真实 runtime state。

### 2.3 Semantic Kernel / Microsoft Agent Framework：参考企业级分层治理

Semantic Kernel / MAF 的价值不是更聪明的 prompt，而是工程组织方式。它把 AI 应用拆成 kernel、service、plugin、function、process、filter 等层。

Holo 可映射为：

```text
HoloKernel
  services:
    model providers
    memory
    retrieval
    journal
    telemetry
    artifact store
    policy
  plugins:
    finance
    math
    physics
    code
    browser
    filesystem
  functions:
    tool manifests
    processor nodes
    verifier functions
  processes:
    AgentGraph
    MissionRuntime
    ResidentWorker
    BenchmarkRunner
  filters:
    schema
    policy
    provenance
    cost
    cache
    citation
    numeric verification
```

这能把 Holo 旧阶段里的 Perception Bus、Memory Fabric、Action Market、Consciousness Ledger 落到更硬的工程抽象上：

| 旧概念 | Kernel v3 应落点 |
| --- | --- |
| Perception Bus | event intake + observation reducer |
| Action Market | tool registry + planner-proposed tool call |
| Memory Fabric | typed memory layers |
| Consciousness Ledger | journal + checkpoint + replay |
| Processor Fabric | graph nodes + plugin/process steps |

不应照搬：

- 不引入过重样板导致迭代变慢。
- 不把 plugin 写成规则系统。
- 不让多 agent 概念掩盖当前最关键的单 agent loop 质量。

### 2.4 Hermes Function Calling：把工具协议彻底标准化

Hermes Function Calling 的核心是朴素但关键的闭环：

```text
model proposes tool_call
host parses and validates schema
host executes allowed function
host returns tool_response
model observes and continues or finalizes
```

Holo 应固化统一协议：

```text
ToolManifest {
  name,
  description,
  args_schema,
  result_schema,
  side_effects,
  authority,
  cost_hint,
  timeout,
  streaming,
  domain_tags
}

ToolCall {
  call_id,
  tool_name,
  arguments,
  purpose,
  expected_observation,
  requested_by_node,
  model_message_ref
}

ToolResult {
  call_id,
  status,
  observation,
  citations,
  artifacts,
  diagnostics,
  retryable,
  cost_usage
}
```

关键要求：

- 工具调用必须结构化，不能从自然语言里猜。
- Host 可以拒绝 schema 错误、权限错误、危险副作用。
- 错误也是 observation，应反馈给模型继续判断。
- 工具数量和上下文要按 task profile 暴露，不要把所有工具一次性塞给所有任务。

### 2.5 HERMES Math Agent：把 verifier 做成模型可调用工具

HERMES Math Agent 最值得 Holo 吸收的点是 verifier-as-tool：

- 模型遇到关键数学声明时主动调用 `verify_one_mathematical_step`。
- 验证器返回 correct / incorrect / inconclusive。
- 验证过的声明可以进入记忆，供后续证明复用。
- agent loop 仍由模型推进，验证器不是 host 替模型思考。

Holo 对应落点：

- 金融里已经将 `finance.verify_numeric` 作为标准 read-only tool 暴露给 planner。
- 数学可以接入 CAS、Lean、SymPy、Z3 或专用 verifier。
- 物理可以接入量纲检查、单位换算、符号推导、数值仿真。
- 代码可以接入 tests、type checker、static analyzer、runtime sandbox。

关键边界：

- Verifier 只验证声明或计算链，不替模型选择最终语义答案。
- Host 只负责调用、记录、校验工具输出。
- 模型继续决定是否修正、继续检索、重新计算或最终回答。

---

## 3. 回看 Holo 开发过程后的真实主线

### 3.1 从对话系统走向 host-owned harness

早期 Holo 更像带记忆、transport 和人格连续性的对话系统。Kernel v3 后，真正核心变成：

```text
用户事件
-> semantic intake
-> task compile
-> planner
-> policy gate
-> tool execution
-> observation
-> evaluator / workloop
-> synthesis / verifier
-> final answer or failure
-> journal / memory proposal
```

这和外部框架的共同方向一致：模型可以提出计划和工具调用，但执行权、权限、审计、状态恢复和停止边界必须由 host 拥有。

### 3.2 从一次性回答走向证据耦合的问题解决

金融题暴露了普通 chat 模型最明显的弱点：

- 找错报表。
- 拿错期间。
- 混淆 revenue、net revenue、operating revenue、total revenues and other income。
- 单位和 scale 错误。
- 把公式中间量和最终量混掉。
- 最终答案看似合理但引用不支持。

因此 Holo 逐步形成了 finance fact ledger、slot frame、FormulaTrace、numeric verifier、citation support、synthesis gate 和 benchmark failure taxonomy。

当前金融能力的目标不是“背答案”，而是：

```text
source-grounded financial reasoning workflow
```

### 3.3 从被动 RAG 走向可管理工作上下文

`KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md` 已经给出关键判断：naive top-k RAG 不够。Holo 需要的是 agent memory：

- event memory：journal 是事实序列。
- thread working set：当前目标、缺口、成功发现、失败尝试。
- durable memory：经 host 审批的用户、项目、任务记忆。
- research graph：query、source、document、evidence、claim 的关系。
- tool memory：工具失败、来源质量、抓取和解析失败经验。
- reflection memory：最终答案或失败后的可复用经验。

这与 LangGraph 的 persistence/store、HERMES 的 verified-claim memory、MemGPT 风格 virtual context 是一条路线：让模型看到正确的工作上下文，而不是把所有历史原文塞进 prompt。

### 3.4 从演示事件列表走向真实 runtime graph

dashboard 的问题很典型：graph 跳动、complete 后仍变动、节点突然一次性导通、UI 和真实 loop 不同步。根因不是 CSS，而是 UI 订阅的不是严格 typed runtime state delta。

下一步 UI 应只渲染真实事件：

```text
graph_created
node_started
tool_call_requested
tool_call_running
tool_result_observed
verifier_result_observed
edge_activated
node_completed
branch_joined
finalized
```

`finalized` 后当前 turn graph 冻结。后续异步统计、memory proposal 或 report update 必须进入 post-run 区域，不能继续污染本 turn 的 running 状态。

### 3.5 从能力展示走向统计闭环

`KERNEL_V3_FINANCE_ABILITY_METRICS_2026-06-15.md` 说明当前本地金融题库不是一个单一集合，而是多个任务族：

- FinanceBench doc retrieval：150 题，主大型金融 benchmark。
- FAB v2 public：27 题，无公开 gold，适合行为和 workflow trace。
- FAB dev10：10 题，有 gold/annotation，适合开发调试。
- Holo workflow challenge：50 题，无 gold，适合覆盖/failure taxonomy。

因此后续报告不能只写“某一道题答对”。必须报告：

- split：debug / holdout / public / no-gold。
- item count。
- pass_rate / numeric_accuracy。
- workflow_score / substrate_score。
- citation_present_rate。
- calculator_used_rate / formula_trace_present_rate。
- verifier tool call rate。
- processor cache hit ratio。
- failure layer counts。

---

## 4. 当前已落地的工程吸收点

| 方向 | 已有落点 | 价值 |
| --- | --- | --- |
| Host-owned loop | `kernel_v3/agent/runtime.py`, `kernel_v3/loop.py`, `PolicyGate`, `ToolRegistry` | 模型提议，host 执行和记录 |
| Processor fabric | `kernel_v3/processors/` | schema-first model packet、usage、JSON repair、provider abstraction |
| Tool protocol | `kernel_v3/tools.py` | schema validation、permission、read-only / side-effect boundary |
| Retrieval workbench | `kernel_v3/retrieval/` | search/fetch/extract/evidence/source quality/workbench judgment |
| Finance domain pack | `kernel_v3/finance/` | fact ledger、target binding、calculator、numeric verifier、synthesis support |
| Verifier-as-tool | `finance.verify_numeric` | planner 可主动调用标准验证工具，而不是 host 后处理替模型选答案 |
| Runtime graph projection | `kernel_v3/runtime_graph.py` | dashboard/CLI 可订阅 typed graph delta 的雏形 |
| Benchmark observability | `kernel_v3/bench/finance.py`, `kernel_v3/bench/report.py` | cache、processor、formula support、failure layer、verifier tool usage统计 |
| Memory/RAG substrate | `kernel_v3/memory/`, `KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md` | durable memory、working set、research graph、reflection proposal |
| UI demo | `kernel_v3/demo_dashboard.py` | chat、runtime console、topology、prompt bank、case selector |

本次追加落地：

- `FinanceBenchmarkSummary` 新增：
  - `finance_verify_numeric_tool_call_count`
  - `finance_verify_numeric_tool_error_count`
  - `finance_verify_numeric_tool_used_rate`
  - `finance_verify_numeric_tool_error_rate`
- `finance-report` Markdown summary 新增 verifier tool 调用、使用率、错误率。
- 聚焦测试覆盖 summary/report 聚合。

这属于观测层，不参与答案选择，不改变 LLM-owned financial reasoning。

---

## 5. Holo 应该参考什么，具体到下一步

### 5.1 AgentGraph Runtime

目标：把当前线性 workloop 升级为 typed graph runtime。

优先级最高的工程动作：

1. 定义 `AgentGraphState` 和 `AgentGraphDelta` 作为第一等 runtime contract。
2. 每个节点输出 typed delta，而不是事后从 journal 猜图。
3. Dashboard、CLI、benchmark report 全部订阅同源 delta。
4. 当前 turn `finalized` 后冻结图，post-run diagnostics 进入独立区域。
5. 支持 branch/join，为并行检索和并行候选验证准备接口。

### 5.2 Standard Tool Protocol

目标：所有工具对 planner 看起来一致。

下一步：

1. 统一 `ToolManifest` 字段：schema、side effect、cost、authority、streaming、domain tags。
2. 统一 `ToolCall` 字段：purpose、expected observation、call id、node ref。
3. 统一 `ToolResult` 字段：status、observation、citations、artifacts、diagnostics、retryable。
4. 工具错误回到模型作为 observation，而不是 host 私下吞掉。
5. 允许 domain pack 提供 tool templates，但禁止 tool templates 变成答案规则。

### 5.3 Domain Pack

目标：金融、数学、物理、代码、研究共享通用 loop，只换工具和上下文。

每个 domain pack 应提供：

- capability manifest；
- tool manifest；
- context compiler；
- prompt contract；
- verifier tools；
- benchmark/eval profile；
- failure taxonomy；
- memory extraction policy。

Finance pack 当前是第一个成熟样板。后续 math pack 可以从 `calculator.compute`、symbolic algebra、proof verifier 开始；physics pack 可以从 unit/dimension checker、formula library、simulation sandbox 开始；code pack 可以从 tests/typecheck/static analysis 开始。

### 5.4 Verifier-as-tool

目标：把验证器从 host 后处理推进为模型可主动调用的标准工具。

金融里的正确形态：

```text
LLM identifies target claim / formula / numeric answer
-> calls finance.verify_numeric with facts, traces, citations, evidence
-> observes passed/failed/issues
-> repairs, searches more, recalculates, or finalizes
```

禁止：

- Host 自己根据关键词决定哪个数字是答案。
- Host 自己选 row、套公式、生成最终答案。
- Gold/reference 泄露到 verifier prompt 或 runtime context。

### 5.5 Memory / Context / Cache

目标：既提高能力，也控制成本。

可参考 LangGraph persistence、MemGPT virtual context、HERMES verified-claim memory。Holo 需要三个同时成立：

- 正确上下文：模型看到当前任务需要的 working set、facts、gaps、tool history。
- 稳定前缀：processor prompt stable prefix 固化，提高 DeepSeek/OpenAI-compatible cache 命中率。
- 可压缩动态区：大文档、长 trace、重复 evidence 用 refs、summaries、support index，而不是全量原文。

下一步：

1. 将 processor prompt 拆成 stable prefix + dynamic packet。
2. 将 finance slot_bind / synthesizer / numeric_judge 的 stable contract 固化。
3. 把 retrieval graph、formula support、citation refs 作为 compact topology 给模型。
4. 记录 cache hit/miss by task type，并用它驱动 prompt packet 改造。

### 5.6 Benchmark / Telemetry

目标：用统计证明能力，用 telemetry 定位瓶颈。

每次多题 run 必须报告：

- item_count、split、dataset；
- pass_rate、numeric_accuracy；
- workflow/substrate score；
- citation_present_rate；
- calculator_used_rate；
- formula_trace_present_rate；
- finance_verify_numeric_tool_used_rate；
- processor_prompt_cache_hit_ratio；
- processor_task_type_counts；
- failure_layer_counts。

debug split 与 holdout split 必须分开。FB 与 FAB 必须分开。无 gold 的 public/challenge set 不能写 accuracy，只能写 workflow/substrate/cost/failure。

### 5.7 UI / Observability

目标：展示真实 agent loop，而不是把 chatgpt 包一层皮。

UI 应展示：

- chat 输入输出；
- runtime console：模型 packet、工具调用、observation、verifier、final/failure；
- graph topology：节点、边、branch/join、active state；
- per-node timing/cost/cache；
- evidence/facts/formula/citations 的结构化链接；
- current turn 和 post-run 区域严格分离。

不要展示：

- 假 topology。
- 后验拼接成“看起来像实时”的事件。
- 过长原始文本导致 UI 失焦。
- 私有模型内部 hidden chain-of-thought 原文。应暴露 public trace、模型可见输入输出、结构化理由、工具调用和观察结果。

---

## 6. 为什么 Holo 只能攻克一部分题，以及通用攻克思路是什么

当前 Holo 不是“越改越弱”，而是进入了更严格、更真实的形态：从能用补丁拿分，转向 LLM-owned、source-grounded、可审计、可泛化。这个转型会暴露更多真实失败。

金融任务的困难主要分层：

1. Source acquisition：找不到正确 filing、URL、表格或 document。
2. Metric binding：同一 metric 名称在公司/行业/报表里口径不同。
3. Period binding：FY、quarter、TTM、calendar year、fiscal year 容易混。
4. Unit/scale binding：thousand/million/billion、percentage、per-share、ratio。
5. Formula planning：slot 缺失、平均值、差值、margin、turnover、DIO、DCF/LBO。
6. Evidence support：答案数字有了，但 citation 不支持。
7. Final synthesis：正确数字和干扰数字同时出现，导致 final answer 不干净。
8. Cost/latency：长文档和多轮检索带来 token 与时间压力。

通用攻克思路不是写规则表，而是让 agent loop 更像专家工作流：

```text
understand task
-> identify required slots and evidence
-> inspect candidates
-> bind metric/period/source
-> calculate if needed
-> verify claim
-> synthesize concise answer
-> record what worked and failed
```

这个结构可迁移：

| 领域 | slot | evidence | transform | verifier |
| --- | --- | --- | --- | --- |
| 金融 | metric、period、company、unit | filing、table、citation | ratio、growth、margin、DCF | numeric verifier |
| 数学 | theorem、assumption、lemma | definitions、prior steps | algebra、proof step | Lean/CAS |
| 物理 | quantity、unit、condition | formula、experiment、constants | derivation、simulation | unit/dimension/numeric check |
| 代码 | bug、file、test、runtime | source、logs、tests | patch、refactor | tests/typecheck/static analysis |
| 研究 | claim、source、facet | paper、report、web evidence | synthesis、comparison | citation/source quality |

---

## 7. Kernel v3.1 建议路线

### Phase A：Graph runtime 收束

- 定义 `AgentGraphState`、`AgentGraphNode`、`AgentGraphEdge`、`AgentGraphDelta`。
- Runtime 执行时直接产生 delta。
- Dashboard/CLI/report 使用同一 delta。
- Turn finalized 后冻结 current graph。

### Phase B：Tool protocol 收束

- 统一工具 manifest 和 result schema。
- 所有 domain tool 都走同一 registry/policy/schema path。
- 工具错误成为模型 observation。
- `finance.verify_numeric` 作为标准 verifier tool 样板继续推广。

### Phase C：Finance pack 强化

- 强化 slot_bind prompt packet，减少 JSON drift。
- 让 planner 自然选择 `retrieval.run -> calculator.compute -> finance.verify_numeric -> respond`。
- 建立 formula support index 与 citation support index 的稳定上下文。
- 在 FB debug 稳定后再跑 FB holdout，不混分。

### Phase D：并行化

- 题目级并行已经可用，下一步是单题内部并行。
- 并行 source search。
- 并行 candidate fact binding。
- 并行 formula hypothesis。
- 并行 verifier / counter-evidence。
- join 节点由 LLM synthesis 或 verifier-guided judge 合并。

### Phase E：Memory / cache / cost

- Prompt stable prefix freeze。
- Processor usage by task type 继续进报告。
- Cache hit ratio 作为长期成本指标。
- Thread working set、tool memory、research graph 进入 planner page-in。
- 错题经验进入 pending memory proposal，不自动污染 durable memory。

### Phase F：Benchmark 统计

- FB debug：offset 0-9，系统调试。
- FB holdout：offset 10-149，评估。
- FAB dev10：开发集。
- FAB public27：公开行为和 workflow trace。
- 每次 run 输出 summary、report、weak items、failure layer、cache metrics。

### Phase G：通用能力恢复

- 简单 chat 不应进入长 finance loop。
- 通用任务走 lightweight semantic/direct profile。
- 文件、代码、检索、数学、物理都复用同一 tool protocol。
- Role play / companion 能力依赖 memory、persona context 和 interaction profile，但不能破坏 host-owned safety boundary。

---

## 8. 报告中可以如何表述

建议主叙述：

> Holo Kernel v3 的核心贡献不是一个金融脚本，而是一个 host-owned agent harness。模型负责语义判断和行动提议，host 负责工具、权限、审计、验证、记忆和停止边界。金融任务被选为第一个高压领域，因为它同时要求检索、证据、表格、指标口径、公式计算、引用和数值验证。

对外部框架的表述：

> 我们参考 LangChain 的组件生态，LangGraph 的 state graph / checkpoint / streaming，Semantic Kernel 的 kernel-plugin-filter 分层，Hermes 的 schema tool-call loop，以及 HERMES Math Agent 的 verifier-as-tool。Holo 不直接包装这些框架，而是吸收其经过验证的架构原则，落成自己的 Kernel v3 harness。

对当前能力的表述：

> 当前 Holo 最稳定的能力是 source-grounded financial fact extraction、metric disambiguation、auditable calculation trace 和 numeric verification。它已经具备真实 live benchmark 证据和可视化 demo，但更困难的 FinanceBench doc retrieval、FAB workflow、DCF/LBO 和复杂多文档研究仍需要继续迭代。

对下一步的表述：

> 下一步重点是 AgentGraph Runtime、标准工具协议、verifier-as-tool、单题内部并行化、上下文压缩和 cache 优化，以及严格区分 debug/holdout 的大规模金融 benchmark。

不建议说：

- “金融问题已经全域解决。”
- “Holo 比所有通用模型都强。”
- “UI 展示了模型私有 chain-of-thought。”
- “所有 benchmark 都是 held-out 高分。”

应该说：

- “Holo 已经形成可审计、可工具调用、可验证、可扩展的 agent harness。”
- “金融是第一个高压 domain pack。”
- “当前已有强 live evidence，但更广 benchmark 仍在迭代。”
- “我们明确禁止 gold 泄露、答案表和关键词规则捷径。”

---

## 9. 最终判断

Holo 这几个月没有白干。真正的成果不是某个 UI 或某个单题分数，而是系统已经具备了成为通用 agent kernel 的骨架：

- host-owned execution boundary；
- LLM-owned semantic decision；
- schema-first processor fabric；
- standard tool registry；
- retrieval workbench；
- finance fact / formula / verifier substrate；
- durable memory and working set；
- benchmark and telemetry；
- dashboard and runtime graph projection。

外部框架给出的启发非常一致：强 agent 不是单个 prompt，而是模型、工具、状态、记忆、验证、观测和成本控制的系统耦合。Kernel v3 下一步要做的，就是把这些已有部件收束成显式 AgentGraph Runtime，并继续用金融题作为高压场景，不断提升真实能力。

