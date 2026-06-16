# Holo Kernel v3 开源框架审阅与开发复盘决策文档

日期：2026-06-16  
分支：`kernel-v3`  
用途：结项报告、讲稿、论文方法章节、Kernel v3.1 工程路线  
状态：落成决策文档。本文件面向报告使用，浓缩外部框架审阅、本地开发过程复盘、可吸收机制和明确行动项。

---

## 0. 核心结论

Holo Kernel v3 不应该变成 LangChain、LangGraph、Semantic Kernel / Microsoft Agent Framework 或 Hermes 的 wrapper。正确路线是保留 Holo 的 host-owned agent harness 定位，吸收这些框架已经验证过的工程原则：

```text
Host-owned AgentGraph Runtime
  + LLM-owned semantic decisions
  + Standard Tool Protocol
  + Processor / Provider Fabric
  + Durable Memory / Working Set / Research Graph
  + Domain Packs
  + Verifier-as-tool
  + Benchmark / Telemetry / UI
```

金融是当前主战场，因为金融题会同时压测检索、来源、表格、口径、期间、单位、公式、引用、验证、成本和最终合成。但金融能力不能写成金融规则脚本。finance pack 应作为第一个高压 domain pack，为数学、物理、代码、研究、文件工作、role play 和系统常驻任务提供可迁移样板。

Kernel v3 的核心不变量继续保持：

- LLM 负责语义判断：任务理解、计划、工具选择、slot binding、证据取舍、公式意图、最终答案。
- Host 负责边界与执行：schema、权限、工具执行、日志、验证、成本、cache、memory、停止条件。
- Gold/reference 只用于 post-run scoring，不能进入 runtime prompt、tool context、retrieval context 或 memory。
- 禁止答案表、关键词拦截、阈值捷径、host 代替模型选择金融事实或最终数字。

---

## 1. 审阅材料

### 1.1 外部框架

本地参考仓库位于 `/tmp/holo_agent_framework_refs/`，已抽读 README 与关键说明；同时核对官方文档/项目源。

| 框架 | 来源 | Holo 可参考点 |
| --- | --- | --- |
| LangChain | <https://docs.langchain.com/oss/python/langchain/overview>, `/tmp/holo_agent_framework_refs/langchain` | provider-agnostic model/tool/retriever/document 接口，structured output，中间件，观测与集成生态 |
| LangGraph | <https://docs.langchain.com/oss/python/langgraph/overview>, `/tmp/holo_agent_framework_refs/langgraph` | long-running stateful agents、durable execution、checkpoint/resume、streaming、interrupt、memory、branch/join |
| Semantic Kernel / Microsoft Agent Framework | <https://learn.microsoft.com/en-us/semantic-kernel/overview/>, `/tmp/holo_agent_framework_refs/semantic-kernel` | kernel/service/plugin/function/process/filter 分层，enterprise observability/security/stable API 思路 |
| Hermes Function Calling | <https://github.com/NousResearch/Hermes-Function-Calling>, `/tmp/holo_agent_framework_refs/hermes-function-calling` | schema tool-call、tool response、JSON mode、recursive observe-act loop |
| HERMES Math Agent | <https://github.com/aziksh-ospanov/HERMES>, `/tmp/holo_agent_framework_refs/hermes-math-agent` | verifier-as-tool、verified claim memory、agent/verifier coupling |
| DeepSeek Context Caching | <https://api-docs.deepseek.com/guides/kv_cache> | stable prefix、prompt cache hit/miss telemetry、长上下文成本纪律 |

### 1.2 Holo 内部开发文档

本次重点复核：

- `docs/KERNEL_V3_AGENT_LOOP.md`
- `docs/KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md`
- `docs/KERNEL_V3_SYSTEM_REVIEW_2026-06-13_ZH.md`
- `docs/KERNEL_V3_PROJECT_STATUS_2026-06-14_ZH.md`
- `docs/KERNEL_V3_FINANCE_ABILITY_METRICS_2026-06-15.md`
- `docs/KERNEL_V3_FB_FAB_EXPERIMENT_SPLITS_2026-06-15.md`
- `docs/KERNEL_V3_PROGRESS_2026-06-15_FINANCE_SLOT_BIND_CACHE.md`
- `docs/KERNEL_V3_PROGRESS_2026-06-16_PROCESSOR_USAGE_CACHE_METRICS.md`
- `docs/PROCESSOR_ROUTING_AND_COST_POLICY.md`
- `docs/HOLO_ARCHITECTURE_MAP.md`
- `AGENTS.md`

这些文档说明：Holo 的一路开发不是单点刷题脚本，而是从对话、记忆、工具、检索、金融基准、可视化和成本观测逐步收敛成 host-owned agent kernel。

---

## 2. 我们能从优秀框架中参考什么

### 2.1 从 LangChain 参考接口生态，而不是接管核心 loop

LangChain 的强项是统一组件接口和集成生态。Holo 应吸收：

- `ModelClient` / processor 的 provider-agnostic 接口。
- tool、retriever、document、loader、splitter、vector store 的清晰边界。
- structured output、middleware、usage tracing、debug/eval/observability。
- 第三方 connector 的适配层，避免所有外部能力都从零写。

落到 Holo：

- `kernel_v3/processors/` 继续作为模型调用与结构化输出层。
- `kernel_v3/tools.py` 与 domain pack 工具稳定为统一 tool protocol。
- `kernel_v3/retrieval/` 继续拆分 provider、loader、extractor、ranker、evidence reducer。
- finance、math、physics、code、workspace、browser 应是 domain/tool pack，而不是散落在 runtime 巨函数里。

不应照搬：

- 不用 LangChain Agent 替代 Holo 的 host-owned loop。
- 不用文本 callback 替代 typed journal。
- 不为了生态便利牺牲权限、审计、防泄漏和 benchmark 边界。

### 2.2 从 LangGraph 参考 AgentGraph Runtime

LangGraph 最关键的思想不是“画流程图”，而是把 agent 变成显式、可恢复、可流式观察的状态机。Kernel v3 目前已有 journal、task graph、runtime graph projection、dashboard 和 benchmark telemetry，但真实执行仍偏线性 workloop。下一阶段最值得落成的是 typed graph runtime。

Holo 应定义：

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

标准节点建议：

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

必须吸收：

- checkpoint / resume / replay：长任务、常驻任务、夜间 benchmark 和中断恢复都需要。
- streaming state delta：dashboard、CLI、benchmark report 应订阅同源 runtime delta。
- interrupt：证据不足、权限、预算、用户确认时能暂停。
- branch / join：并行检索、候选事实、候选公式、反证、验证器可并行。
- memory/store：thread working set、durable memory、research graph 是 graph state 的组成部分。

禁止事项：

- 不用 graph edge 写金融关键词规则。
- 不让 host edge 条件决定哪个金融数字是答案。
- 不为了 demo 画假 topology。UI 只能渲染真实 runtime state。

### 2.3 从 Semantic Kernel / MAF 参考分层治理

Semantic Kernel / Microsoft Agent Framework 的价值在于工程组织：kernel 管服务，plugin 管能力，function 管可调用单元，process 管长流程，filter 管前后置治理。

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
    AgentGraphRuntime
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

这能把旧阶段概念落成更硬的工程抽象：

| 旧概念 | Kernel v3 落点 |
| --- | --- |
| Perception Bus | event intake + observation reducer |
| Action Market | tool registry + planner-proposed tool call |
| Memory Fabric | typed memory layers |
| Consciousness Ledger | journal + checkpoint + replay |
| Processor Fabric | graph nodes + plugin/process steps |

不应照搬：

- 不引入过重样板，导致今晚/近期金融迭代变慢。
- 不把 plugin 写成规则系统。
- 不让多 agent 名词掩盖当前最关键的单 agent loop 质量。

### 2.4 从 Hermes Function Calling 参考工具协议

Hermes Function Calling 的可参考点很朴素但关键：

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
  cost_usage,
  cache_status
}
```

关键要求：

- 工具调用必须结构化，不能从自然语言里猜。
- Host 可以拒绝 schema 错误、权限错误、危险副作用。
- 错误也是 observation，应反馈给模型继续判断。
- 工具数量和上下文按 task profile 暴露，不要把所有工具一次性塞给所有任务。
- 简单问候、普通聊天和无需工具的任务必须允许模型直接回答，不能默认拖进长金融 loop。

### 2.5 从 HERMES Math Agent 参考 verifier-as-tool

HERMES Math Agent 的关键不是数学本身，而是 verifier-as-tool：

```text
LLM makes a non-trivial claim
LLM calls verifier tool
Verifier returns correct / incorrect / inconclusive
LLM revises or continues
Host records verified claims
```

金融场景映射：

| HERMES 数学 | Holo 金融 |
| --- | --- |
| proof step | financial claim / formula step |
| Lean verifier | numeric verifier / citation verifier / formula trace verifier |
| verified claim memory | verified finance claim ledger |
| inconclusive | insufficient evidence / unsupported citation |
| hallucinated proof step | wrong metric, wrong period, wrong unit, unsupported number |

Holo 已有 `finance.verify_numeric`，下一步应把它作为 loop 内标准 verifier tool，而不是后验判分感的附属物。后续可扩展：

- `finance.verify_citation_support`
- `finance.verify_formula_inputs`
- `finance.verify_period_metric_binding`
- math 的 CAS/Lean/SymPy/Z3 verifier
- physics 的 unit/dimension checker 和 simulation verifier
- code 的 test/typecheck/static analyzer verifier

边界：

- verifier 只验证声明、计算链或证据支持，不替模型选择最终语义答案。
- 模型根据 verifier 观察决定修正、继续检索、重新计算或最终回答。
- Host 负责调用、记录、校验工具输出。

### 2.6 从 DeepSeek Cache 参考 prompt 经济学

Context caching 直接影响 Holo 的常驻成本、速度和长上下文可行性。Holo 不应单纯追求少 token，而应追求稳定 prefix 的高 cache 命中。

落地原则：

- stable prefix 前置：system contract、tool manifest、domain policy、schema、source policy。
- dynamic packet 后置：当前 question、observation、facts、gaps、trace。
- 大文档和长 evidence 用 refs、support index、summary，不反复塞全量原文。
- benchmark report 按 processor/task type 统计 cache hit ratio。
- cache 优化不能把 gold、答案表或不可泛化提示塞进 prefix。

本地已有落点：

- `kernel_v3/processors/usage.py` 汇总 provider usage 与 cache。
- `kernel_v3/bench/finance.py` 和 `kernel_v3/bench/report.py` 汇总金融 benchmark processor/cache 指标。
- `docs/KERNEL_V3_PROGRESS_2026-06-16_PROCESSOR_USAGE_CACHE_METRICS.md` 记录 processor usage/cache/report 观测改造。

---

## 3. 回看 Holo 开发过程后的真实主线

### 3.1 从聊天系统走向 host-owned harness

早期 Holo 更像带记忆、transport 和人格连续性的对话系统。Kernel v3 后，真正核心变成：

```text
用户事件
-> semantic intake
-> task compile
-> context page-in
-> planner
-> policy gate
-> tool execution
-> observation
-> evaluator / workloop
-> verifier / repair
-> synthesis
-> final answer or failure
-> journal / memory proposal
```

这与 LangGraph、Semantic Kernel、Hermes 的共同方向一致：模型可以提出计划和工具调用，但执行权、权限、审计、状态恢复和停止边界必须由 host 拥有。

### 3.2 从一次性回答走向证据耦合的问题解决

金融题暴露了普通 chat 模型的主要弱点：

- 找错 filing、报告或来源。
- 拿错 fiscal period。
- 混淆 revenue、net revenue、operating revenue、total revenues and other income。
- 单位和 scale 错误。
- 把公式中间量和最终量混掉。
- 最终答案看似合理但 citation 不支持。

因此 Holo 逐步形成了 retrieval workbench、finance fact ledger、slot frame、FormulaTrace、numeric verifier、citation support、synthesis gate 和 benchmark failure taxonomy。

当前金融能力目标不是背答案，而是：

```text
source-grounded financial reasoning workflow
```

### 3.3 从被动 RAG 走向可管理工作上下文

`KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md` 的判断仍然正确：naive top-k RAG 不是目标。Holo 需要 agent memory：

- event memory：journal 是事实序列。
- thread working set：当前目标、缺口、成功发现、失败尝试。
- durable memory：经 host 审批的用户、项目、任务记忆。
- research graph：query、source、document、evidence、claim 的关系。
- tool memory：工具失败、来源质量、抓取和解析失败经验。
- reflection memory：最终答案或失败后的可复用经验。

这与 LangGraph persistence/store、HERMES verified-claim memory、MemGPT virtual context 是一条路线：让模型看到正确的 compact working context，而不是把所有历史原文塞进 prompt。

### 3.4 从演示事件列表走向真实 runtime graph

Dashboard 曾经出现 graph 跳动、complete 后仍变动、节点突然一次性导通、UI 与实际 loop 不同步。根因不是单纯 CSS，而是 UI 订阅的不是严格 typed runtime state delta。

下一步原则：

```text
Runtime state is source of truth.
Journal delta is transport.
Graph UI is projection.
Finalized turn is frozen.
Post-run stats are separate from current turn.
```

UI 应显示真实节点生命周期：

```text
graph_created
node_started
tool_call_requested
tool_call_running
tool_result_observed
verifier_result_observed
edge_activated
branch_joined
node_completed
finalized
```

`finalized` 后当前 turn graph 冻结。后续异步统计、memory proposal、report update 进入 post-run 区域，不能污染 current turn running 状态。

### 3.5 从能力展示走向统计闭环

本地金融题库不是单一集合：

| Track | Path | Count | Gold/annotation | 用途 |
| --- | --- | ---: | --- | --- |
| FinanceBench doc retrieval | `data/bench/finance/financebench_doc_retrieval.jsonl` | 150 | 有 gold/sidecar | 主大型金融 benchmark |
| FAB v2 public | `data/bench/finance/fabv2_public.jsonl` | 27 | 无公开 gold | public behavior/substrate/cost/failure taxonomy |
| FAB dev10 | `data/bench/finance/fabv2_dev10.jsonl` | 10 | 有 gold/annotation | 小型开发调试集 |
| Holo workflow challenge | `data/bench/finance/holo_finance_workflow_challenge.jsonl` | 50 | 无 gold | workflow stress/demo challenge |

报告时必须区分：

- debug / holdout / public / no-gold。
- FB 与 FAB。
- answer accuracy 与 workflow/substrate/cost/failure taxonomy。
- live 结果与 fake/oracle harness test。

---

## 4. 当前已落地的工程吸收点

| 方向 | 已有落点 | 价值 |
| --- | --- | --- |
| Host-owned loop | `kernel_v3/agent/runtime.py`, `kernel_v3/loop.py`, `PolicyGate`, `ToolRegistry` | 模型提议，host 执行、记录、验证 |
| Processor fabric | `kernel_v3/processors/` | schema-first model packet、provider abstraction、usage、JSON repair |
| Tool protocol | `kernel_v3/tools.py` | schema validation、permission、read-only / side-effect boundary |
| Retrieval workbench | `kernel_v3/retrieval/` | search/fetch/extract/evidence/source quality/workbench judgment |
| Finance domain pack | `kernel_v3/finance/` | fact ledger、target binding、calculator、numeric verifier、synthesis support |
| Verifier-as-tool | `finance.verify_numeric` | planner 可主动调用标准验证工具 |
| Runtime graph projection | `kernel_v3/runtime_graph.py` | dashboard/CLI 订阅 typed graph delta 的雏形 |
| Benchmark observability | `kernel_v3/bench/finance.py`, `kernel_v3/bench/report.py` | cache、processor、formula support、failure layer、verifier tool usage |
| Memory/RAG substrate | `kernel_v3/memory/`, memory/RAG docs | durable memory、working set、research graph、reflection proposal |
| UI demo | `kernel_v3/demo_dashboard.py` | chat、runtime console、topology、prompt bank、case selector |

这些能力多数属于观测、协议、压缩和验证层，不参与答案选择，不改变 LLM-owned financial reasoning。

---

## 5. 为什么 Holo 目前只能攻克一部分题

当前 Holo 的主要矛盾不是“完全没有能力”，而是从补丁式拿分进入更严格、更真实的形态：LLM-owned、source-grounded、可审计、可泛化。这会暴露更多真实失败。

金融任务失败通常分层发生：

1. Source acquisition：找不到正确 filing、URL、表格或 document。
2. Metric binding：同一 metric 名称在公司/行业/报表里口径不同。
3. Period binding：FY、quarter、TTM、calendar year、fiscal year 容易混。
4. Unit/scale binding：thousand/million/billion、percentage、per-share、ratio。
5. Formula planning：slot 缺失、平均值、差值、margin、turnover、DIO、DCF/LBO。
6. Evidence support：答案数字有了，但 citation 不支持。
7. Final synthesis：正确数字和干扰数字同时出现，最终答案不干净。
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

该结构可迁移：

| 领域 | slot | evidence | transform | verifier |
| --- | --- | --- | --- | --- |
| 金融 | metric、period、company、unit | filing、table、citation | ratio、growth、margin、DCF | numeric/citation verifier |
| 数学 | theorem、assumption、lemma | definitions、prior steps | algebra、proof step | Lean/CAS/SymPy/Z3 |
| 物理 | quantity、unit、condition | formula、experiment、constants | derivation、simulation | unit/dimension/numeric check |
| 代码 | bug、file、test、runtime | source、logs、tests | patch、refactor | tests/typecheck/static analysis |
| 研究 | claim、source、facet | paper、report、web evidence | synthesis、comparison | citation/source quality |

---

## 6. Kernel v3.1 建议落成路线

### Phase A：AgentGraph Runtime

目标：把当前线性 workloop 升级为 typed graph runtime。

行动：

1. 定义 `AgentGraphState`、`AgentGraphNode`、`AgentGraphEdge`、`AgentGraphDelta`。
2. 每个 runtime 节点执行时直接输出 typed delta，而不是 UI 事后从 journal 猜图。
3. Dashboard、CLI、benchmark report 全部订阅同源 delta。
4. 当前 turn `finalized` 后冻结图。
5. 支持 branch/join，为单题内部并行检索和候选验证准备接口。

### Phase B：Standard Tool Protocol

目标：所有工具对 planner 看起来一致。

行动：

1. 统一 `ToolManifest` 字段：schema、side effect、cost、authority、streaming、domain tags。
2. 统一 `ToolCall` 字段：purpose、expected observation、call id、node ref。
3. 统一 `ToolResult` 字段：status、observation、citations、artifacts、diagnostics、retryable、cache status。
4. 工具错误回到模型作为 observation，而不是 host 私下吞掉。
5. domain pack 可以提供 tool templates，但 tool templates 不能变成答案规则。

### Phase C：Finance Pack 强化

目标：提升真实金融做题能力，不靠规则作弊。

行动：

1. 强化 LLM-owned `task.compile -> finance.slot_bind -> calculator.compute -> finance.verify_numeric -> synthesize` 链路。
2. 保持 formula support index、citation support index、fact ledger compact 进入 prompt。
3. 让 verifier issue codes 成为模型可读 repair hints。
4. 在 FB debug split 稳定后再跑 FB holdout；FAB 单独报告。
5. 对无 gold public/challenge set 只报 workflow/substrate/cost/failure，不报 accuracy。

### Phase D：Memory / Context Page-In

目标：让模型看到正确上下文，同时控制成本。

行动：

1. 将 processor prompt 拆成 stable prefix + dynamic packet。
2. 将 thread working set、research graph、tool memory 页入 planner。
3. 将 failed attempts、source-family outcomes、verified claims 进入 compact working state。
4. durable memory 只通过 host-managed recall 或审批后的 context injection 进入模型。
5. post-task reflection 形成待审核 memory proposal。

### Phase E：Parallel Branching

目标：用并行提升 hard finance 与研究任务效率。

适合并行：

- 多来源检索。
- 多候选 metric/period 假设。
- 多公式路径。
- verifier/counterexample 检查。
- benchmark item-level parallel。

不适合并行：

- 简单 greeting。
- 单步 direct answer。
- 无工具需求的普通聊天。
- 已有充分证据后的重复检索。

并行后的合并仍由 LLM 做语义判断。Host 只负责并行执行、去重、压缩观察、验证 provenance 和统计成本。

### Phase F：Dashboard / Observability

目标：展示真实 agent loop，而不是把 ChatGPT 包一层皮。

UI 应显示：

- chat 输入输出。
- runtime console：model packet、tool call、observation、verifier、final/failure。
- graph topology：节点、边、branch/join、active state。
- per-node timing/cost/cache。
- evidence/facts/formula/citations 的结构化链接。
- current turn 与 post-run diagnostics 严格分离。

UI 不应显示：

- 虚构 topology。
- complete 后仍跳动的 current graph。
- 与当前 turn 无关的历史事件污染。
- 大量难读原始文本。
- 私有模型内部 hidden chain-of-thought 原文。应暴露 public trace、模型可见输入输出、结构化理由、工具调用和观察结果。

---

## 7. 明确禁止的路线

为了保持 Holo 的真实能力，以下路线不能再回头：

- 用关键词判断题型、metric、period、答案数字。
- 用阈值或打表代替模型 slot binding。
- host 自己选金融事实、套公式、生成答案。
- 把 gold/reference 泄露给 runtime。
- 将 debug split 结果包装成 holdout。
- 为 demo 画假 agent topology。
- 让简单任务强行进入长金融 loop。
- 用 fake offline 结果冒充 live 能力。
- 让 UI 或 scorer 反过来污染 agent loop。

允许并且应强化：

- schema validation。
- policy gate。
- tool permission。
- deterministic calculator。
- citation/numeric/provenance verifier。
- benchmark post-run scoring。
- typed journal。
- cache/cost telemetry。
- split discipline。

区别在于：这些 host 能力是边界、执行和验证，不是语义答案选择。

---

## 8. 报告/讲稿可用表述

可直接使用：

> Holo Kernel v3 的定位不是另一个 LangChain wrapper，而是一个 host-owned agent kernel。它吸收 LangGraph 的 state graph 和 durable execution，吸收 Semantic Kernel / Microsoft Agent Framework 的 plugin/process/filter 分层，吸收 Hermes 的 schema tool-call loop，吸收 HERMES Math Agent 的 verifier-as-tool 思想。金融 benchmark 是当前压力测试场：模型负责理解问题、选择证据、绑定口径、合成答案；host 负责工具执行、日志、验证、记忆、成本和停止边界。

项目价值可这样讲：

- 我们不是在做金融题脚本，而是在做可迁移的高智力 agent harness。
- 金融能力是 proof-of-capability：它要求检索、证据、计算、引用、验证全链路。
- 通用能力来自同一套 agent loop：领域能力通过 domain pack 扩展。
- 可视化不是装饰，它是 runtime graph 的观测窗口。
- 下一阶段提升方向是 AgentGraph、上下文压缩、工具链强化、verifier-as-tool、memory/page-in、并行化和 cache telemetry。

---

## 9. 最短执行清单

下一轮工程优先级建议：

1. 定义 `AgentGraphState` 和 `GraphDelta` schema。
2. 把当前 planner/tool/evaluator/synthesizer 映射成 graph nodes。
3. 固化 `ToolManifest -> ToolCall -> ToolResult`。
4. 把 finance verifier 扩展为 loop 内 verifier tools。
5. 让 dashboard 订阅 graph delta，而不是事后拼 journal。
6. 将 `thread_working_set + research_graph + tool_memory` 页入 planner。
7. 增加单题内部并行检索/候选事实/候选公式分支。
8. 用 processor usage 按 task type 统计 cache 命中率和失败层。
9. 在 FB debug split 修复后，再跑 FB holdout；FAB 单独报告。
10. 把通用 gauntlet 与 finance benchmark 共用失败分类和成本统计。

这条路线兼顾真实金融能力、通用 agent 能力、可视化、成本和论文可解释性。
