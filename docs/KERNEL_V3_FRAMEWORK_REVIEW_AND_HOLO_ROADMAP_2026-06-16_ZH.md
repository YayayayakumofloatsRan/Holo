# Holo Kernel v3 开源框架审阅与架构落成路线

日期：2026-06-16  
分支：`kernel-v3`  
用途：报告讲稿、论文方法章节、下一轮工程迭代路线

---

## 0. 总结论

审阅 LangChain、LangGraph、Semantic Kernel / Microsoft Agent Framework、Hermes Function Calling、HERMES Math Agent，并复核 Holo Kernel v3 一路开发文档后，结论很清楚：

**Holo 不应变成任何现成框架的 wrapper。Holo 应吸收这些框架已经验证过的架构原则，落成一个 host-owned、LLM-driven、tool-coupled、memory-aware、graph-observable 的通用 agent kernel。**

金融是当前主战场，因为金融题同时压测检索、证据、表格、口径、单位、公式、引用、验证、成本和最终合成。但金融能力不能写成金融规则脚本。正确形态是：

```text
Holo AgentGraph Runtime
  + Standard Tool Protocol
  + Processor / Provider Fabric
  + Durable Memory / Working Set / Research Graph
  + Domain Packs
  + Verifier-as-tool
  + Benchmark / Telemetry / UI
```

其中 finance pack 是第一个高压 domain pack。未来数学、物理、代码、研究、文件工作、role play 和系统常驻任务，都应该共享同一套 agent loop。

硬不变量保持不变：

- LLM 负责语义判断、计划、slot binding、证据取舍、答案合成。
- Host 负责 schema、权限、工具执行、日志、验证、成本、cache、memory 和停止边界。
- Gold/reference 只用于 post-run scoring，不能进入 runtime prompt、memory、retrieval context 或 tool context。
- 禁止答案表、关键词拦截、阈值捷径、host 代替模型选择金融事实或最终数字。

---

## 1. 审阅材料

### 1.1 外部框架

本地参考仓库位于 `/tmp/holo_agent_framework_refs`。

| 框架 | 官方来源 | 本地路径 | 对 Holo 的主要参考 |
| --- | --- | --- | --- |
| LangChain | <https://github.com/langchain-ai/langchain> | `/tmp/holo_agent_framework_refs/langchain` | 模型、工具、检索、文档、集成、observability 的接口生态 |
| LangGraph | <https://github.com/langchain-ai/langgraph> | `/tmp/holo_agent_framework_refs/langgraph` | state graph、durable execution、stream、interrupt、memory、replay |
| Semantic Kernel / Microsoft Agent Framework | <https://github.com/microsoft/semantic-kernel> | `/tmp/holo_agent_framework_refs/semantic-kernel` | kernel/service/plugin/function/process/filter 分层治理 |
| Hermes Function Calling | <https://github.com/NousResearch/Hermes-Function-Calling> | `/tmp/holo_agent_framework_refs/hermes-function-calling` | schema tool-call loop、JSON mode、recursive tool response |
| HERMES Math Agent | <https://github.com/aziksh-ospanov/HERMES> | `/tmp/holo_agent_framework_refs/hermes-math-agent` | verifier-as-tool、单步验证、已验证声明记忆 |

### 1.2 Holo 内部文档

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
- `docs/PROVIDER_COMPATIBILITY_CONTRACT.md`
- `AGENTS.md`

---

## 2. 外部框架可以参考什么

### 2.1 LangChain：参考接口生态，不接管核心 loop

LangChain 的强项是统一组件接口和集成生态。Holo 应吸收：

- model、embedding、reranker、structured output 的 provider-agnostic 接口；
- tool、retriever、document、loader、splitter、vector store 的边界；
- callback、usage、trace、eval 的观测思想；
- 第三方 connector 的适配模式。

落到 Holo：

- `kernel_v3/processors` 继续作为统一模型调用层；
- `kernel_v3/retrieval` 明确拆分 provider、loader、extractor、ranker、evidence reducer；
- finance、math、physics、code、workspace、browser 成为 domain/tool pack，而不是散落在 runtime 巨函数里。

不应照搬：

- 不用 LangChain Agent 替代 Holo 的 host-owned loop；
- 不用文本 callback 替代 typed journal；
- 不为生态便利牺牲安全边界和审计能力。

### 2.2 LangGraph：最重要的 runtime 参考

LangGraph 最值得吸收。它的核心不是“画流程图”，而是让 agent 成为显式、可恢复、可流式观察的状态机。

Holo 下一步应落成：

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

必须吸收：

- checkpoint / resume / replay：长任务、系统常驻、夜间 benchmark 都需要恢复能力；
- stream state delta：dashboard、CLI、benchmark report 必须订阅同源 runtime delta；
- interrupt：证据不足、权限、预算、用户确认时能暂停；
- branch / join：检索、候选事实、候选公式、反证、验证器应可并行；
- memory integration：thread working set、durable memory、research graph 都应进入 graph state。

禁止事项：

- 不用 graph edge 写关键词规则；
- 不让 host edge 条件决定哪个金融数字是最终答案；
- 不为了 demo 画假 topology，UI 只能渲染真实 runtime state。

### 2.3 Semantic Kernel / Microsoft Agent Framework：参考分层治理

Semantic Kernel / MAF 的价值是企业级工程组织。

Holo 可映射为：

```text
HoloKernel
  services:
    model providers
    memory
    retrieval
    journal
    telemetry
    policy
  plugins:
    finance
    math
    physics
    code
    workspace
    browser
  functions:
    ToolManifest + ProcessorNode
  processes:
    AgentGraph / MissionRuntime / ResidentWorker
  filters:
    schema
    policy
    provenance
    cost
    cache
    citation
    numeric verifier
```

这能把 Holo 旧阶段里的 Perception Bus、Memory Fabric、Action Market、Consciousness Ledger 落到更硬的工程抽象上：

| 旧概念 | Kernel v3 应落点 |
| --- | --- |
| Perception Bus | event intake + observation reducer |
| Action Market | tool registry + planner-proposed tool call |
| Memory Fabric | typed memory layers |
| Consciousness Ledger | journal + checkpoint + replay |
| Processor Fabric | graph nodes + plugins + process steps |

不应照搬：

- 不引入过重样板导致迭代变慢；
- 不把 plugin 写成规则系统；
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
  tool_name,
  arguments,
  purpose,
  expected_observation,
  stop_or_continue_hint
}

ToolResult {
  ok,
  observation,
  evidence_refs,
  artifacts,
  usage,
  error
}
```

金融场景中，SEC retrieval、companyfacts lookup、filing fetch、table extraction、calculator、numeric judge、citation validator 都应是统一工具或 verifier node，而不是特殊分支。

### 2.5 HERMES Math Agent：verifier-as-tool 是能力放大器

HERMES Math Agent 最重要的思想不是“数学专用”，而是：

```text
LLM makes a non-trivial claim
LLM calls verifier tool
Verifier returns correct / incorrect / inconclusive
LLM revises or continues
Host records verified claims
```

这正好映射到 Holo 的金融与通用能力：

| HERMES 数学 | Holo 金融 |
| --- | --- |
| proof step | financial claim / formula step |
| Lean verifier | numeric verifier / citation verifier / formula trace verifier |
| verified claim memory | verified finance claim ledger |
| inconclusive | insufficient evidence / unsupported citation |
| hallucinated step | wrong metric, wrong period, wrong unit, unsupported answer |

下一步 finance pack 应让 verifier 更像工具：

- `finance.verify_numeric`
- `finance.verify_citation_support`
- `finance.verify_formula_inputs`
- `finance.verify_period_metric_binding`

关键是：verifier 不替模型做最终判断，而是把可验证反馈交回模型，让模型修正自己的计划和答案。

---

## 3. Holo 一路开发过程的真实主线

复核近期文档后，Holo 的演进不是功能堆叠，而是四条主线。

### 3.1 从聊天系统走向 host-owned harness

Kernel v3 的主线已经变成：

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

这说明 Holo 已经不是简单聊天 UI，而是一个可以审计、可以验证、可以接工具、可以恢复的任务执行基座。

### 3.2 从一次性回答走向证据耦合的问题解决

金融题暴露了普通 LLM 的弱点：

- 找错报告或来源；
- 拿错 fiscal period；
- 混淆 revenue、net revenue、operating revenue、total revenue and other income；
- 单位、scale、百万/十亿错误；
- 公式中间值和最终值混淆；
- 答案看似合理但 citation 不支持。

因此 Holo 形成了 retrieval workbench、finance fact ledger、slot frame、FormulaTrace、numeric verifier、citation support、synthesis gate 和 benchmark failure taxonomy。

这条线应继续强化，而不是退回规则脚本。

### 3.3 从被动 RAG 走向可管理工作上下文

`KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md` 的判断是正确的：naive top-k RAG 不是目标。Holo 需要 agent memory：

- event memory：journal 是事实序列；
- thread working set：当前目标、缺口、成功发现、失败尝试；
- durable memory：经 host 管理的用户/项目/任务记忆；
- research graph：query、source、document、evidence、claim 的关系；
- tool memory：工具失败、来源质量、抓取和解析失败经验；
- reflection memory：最终答案或失败后的可复用经验。

这会直接影响能力和成本：模型看到正确的 compact context，远比塞入大量原文更有效。

### 3.4 从演示事件列表走向真实 runtime graph

Dashboard 之前出现过 graph 跳动、complete 后仍变动、节点突然一次性导通、UI 与实际 loop 不同步。根因不是单纯前端样式，而是 UI 没有订阅严格 typed runtime state delta。

下一步 UI 的原则：

```text
Runtime state is source of truth.
Journal delta is transport.
Graph UI is a projection.
Finalized turn is frozen.
Post-run stats are separate from current turn.
```

---

## 4. 推荐的 Kernel v3.1 架构

### 4.1 分层结构

```text
HoloKernel
  AgentGraphRuntime
    AgentGraphState
    GraphNode
    CheckpointStore
    StreamDeltaBus
  ProcessorFabric
    ModelClient
    ProcessorContract
    StructuredRepair
    UsageLedger
  ToolProtocol
    ToolManifest
    ToolCall
    ToolResult
    ToolError
  MemorySystem
    Journal
    ThreadWorkingSet
    DurableMemory
    ResearchGraph
    ToolMemory
  DomainPacks
    FinancePack
    MathPack
    PhysicsPack
    CodePack
    WorkspacePack
  VerifierLayer
    NumericVerifier
    CitationVerifier
    FormulaTraceVerifier
    ProofStepVerifier
  Observability
    BenchmarkSummary
    ProcessorUsage
    CacheMetrics
    FailureTaxonomy
    DashboardGraph
```

### 4.2 Finance pack 应具备的真实能力

金融子系统下一步应重点坐实：

- LLM-owned `task.compile`：模型理解题目、输出需要的事实、公式和证据约束；
- LLM-owned slot binding：模型绑定 metric、period、entity、unit、source；
- tool-backed retrieval：SEC/EDGAR/companyfacts/filing/table/source directory；
- formula trace：每一步计算有 input fact ids、evidence refs、citation refs；
- verifier-as-tool：numeric、citation、formula、period/metric support；
- synthesis repair：最终答案不支持时，模型基于 compact trace 修复；
- benchmark split：debug 和 holdout 明确分开；
- cost/cache metrics：每个 processor、每类任务都可统计。

### 4.3 通用能力应共享同一套 loop

Holo 的目标仍然是系统常驻工作 agent，金融只是当前最硬的能力验证场。通用能力应覆盖：

- 普通问答和轻量 chat：不应陷入长检索 loop；
- workspace/code/file：能临时组装工具链解决工程任务；
- 研究任务：能检索、阅读、引用、合成报告；
- 数学/物理：能分解问题、调用计算/证明/验证工具；
- role play 和 companion：需要 thread continuity、persona/style memory，但不能破坏 host 边界；
- 常驻任务：scheduler、resident worker、提醒、后续行动、记忆提案。

关键是统一：

```text
observe -> judge -> call tool -> observe -> judge -> finalize
```

领域差异只体现在 tool pack、context contract、verifier 和 benchmark，而不是每个领域写一套 host 规则。

---

## 5. 接下来最应落地的工程动作

### 5.1 AgentGraphRuntime

建立真实 graph runtime，不只是 UI graph。

- 每个节点 typed input/output。
- 每次状态变化写 journal delta。
- 支持 checkpoint/resume/replay。
- 支持 branch/join。
- finalized 后冻结当前 turn graph。

### 5.2 标准 Tool Protocol

统一所有工具接口：

- 所有工具有 manifest；
- planner 只能提出 schema-valid tool call；
- tool result 成为 observation；
- tool error 也成为 observation；
- host 执行权限与副作用边界；
- UI 和 benchmark 可直接渲染 tool lifecycle。

### 5.3 Verifier-as-tool

把金融 verifier 从“后验判分感”改成 agent loop 内部可调用能力。

- 模型可主动调用 verifier；
- verifier 只返回支持/不支持/不确定与证据缺口；
- 模型根据结果修复计划或答案；
- host 记录 verifier trace。

### 5.4 Memory / Context Page-In

把 memory 从被动摘要升级为可管理工作上下文。

- thread working set 每轮更新；
- research graph 摘要进入 planner；
- tool failure memory 指导模型避免重复；
- durable memory 只通过 host-managed recall 进入；
- post-task reflection 形成待审核 memory proposal。

### 5.5 Parallel Branching

并行化应服务于能力，不是盲目加发包。

适合并行：

- 多来源检索；
- 多候选 metric/period 假设；
- 多公式路径；
- verifier 检查；
- benchmark item-level parallel。

不适合并行：

- 简单 greeting；
- 单步 direct answer；
- 无工具需求的普通聊天；
- 已有充分证据后的重复检索。

并行后的合并仍应由 LLM 做语义判断，host 只合并结构、去重、验证 provenance。

### 5.6 Cache / Cost Discipline

成本优化的核心不是盲目少 token，而是提高 cache 命中率和减少重复无效 loop。

建议：

- 稳定 system prompt、tool manifest、processor contract 的 prefix；
- 动态 evidence、question、journal delta 后置；
- task type 级统计 cache hit/miss；
- 对 `task.compile`、`finance.slot_bind`、`synthesizer.answer` 分别看 cache；
- 对普通 chat 使用短 loop；
- 对 hard finance 使用 deep profile，但必须有 stop policy。

### 5.7 Dashboard / Demo UI

UI 应暴露真实工作流，而不是长文本堆叠。

应显示：

- 当前 turn graph；
- 节点状态：pending/running/blocked/completed/failed；
- 工具调用与 observation；
- verifier feedback；
- evidence/claim/formula trace；
- cost/cache/time；
- final answer；
- post-run diagnostics。

不应显示：

- 虚构 topology；
- complete 后继续变动的 running graph；
- 与 current turn 无关的历史事件污染；
- 大量难读原始文本。

---

## 6. 明确禁止的路线

为了保持 Holo 的真实能力，以下路线不能再回头：

- 用关键词判断题型、metric、period、答案数字；
- 用阈值或打表代替模型 slot binding；
- host 自己选金融事实、套公式、生成答案；
- 把 gold/reference 泄露给 runtime；
- 将 debug split 结果包装成 holdout；
- 为 demo 画假 agent topology；
- 让简单任务强行进入长金融 loop；
- 用 fake offline 结果冒充 live 能力；
- 让 UI 或 scorer 反过来污染 agent loop。

允许并且应强化：

- schema validation；
- policy gate；
- tool permission；
- deterministic calculator；
- citation/numeric/provenance verifier；
- benchmark post-run scoring；
- typed journal；
- cache/cost telemetry；
- split discipline。

区别在于：这些 host 能力是边界、执行和验证，不是语义答案选择。

---

## 7. 报告/讲稿可用表述

可以这样概括：

> Holo Kernel v3 的定位不是另一个 LangChain wrapper，而是一个 host-owned agent kernel。它吸收 LangGraph 的 state graph 和 durable execution，吸收 Semantic Kernel 的 plugin/process/filter 分层，吸收 Hermes 的 schema tool-call loop，吸收 HERMES Math Agent 的 verifier-as-tool 思想。金融 benchmark 是当前压力测试场：模型负责理解问题、选择证据、绑定口径、合成答案；host 负责工具执行、日志、验证、记忆、成本和停止边界。

项目价值应这样讲：

- 我们不是在做金融题脚本，而是在做可迁移的高智力 agent harness。
- 金融能力是 proof-of-capability：它要求检索、证据、计算、引用、验证全链路。
- 通用能力来自同一套 agent loop：领域能力通过 domain pack 扩展。
- 可视化不是装饰，它是 runtime graph 的观测窗口。
- 未来提升方向是 agent loop 并行化、上下文压缩、工具链强化、memory 和 verifier 深度耦合。

---

## 8. 最短执行路线

下一轮工程优先级建议：

1. 定义 `AgentGraphState` 和 `GraphDelta` schema。
2. 把当前 planner/tool/evaluator/synthesizer 映射成 graph nodes。
3. 固化 `ToolManifest -> ToolCall -> ToolResult`。
4. 把 finance verifier 暴露成 loop 内 verifier tools。
5. 让 dashboard 订阅 graph delta，而不是事后拼 journal。
6. 将 `thread_working_set + research_graph + tool_memory` 页入 planner。
7. 增加单题内部并行检索/候选事实/候选公式分支。
8. 用 processor usage 按 task type 统计 cache 命中率和失败层。
9. 在 FB debug split 修复后，再跑 FB holdout；FAB 单独报告。
10. 把通用 gauntlet 与 finance benchmark 共用失败分类和成本统计。

这条路线兼顾真实金融能力、通用 agent 能力、可视化、成本和论文可解释性。

