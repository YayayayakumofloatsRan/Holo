# Holo Kernel v3 开源框架审阅综合结论与下一步落地

日期：2026-06-16  
分支：`kernel-v3`  
用途：项目报告、讲稿、后续工程路线、金融能力和通用 agent loop 迭代依据

---

## 0. 执行结论

审阅 LangChain、LangGraph、Semantic Kernel / Microsoft Agent Framework、Hermes Function Calling、HERMES Math Agent，并复核 Holo Kernel v3 最近一路开发文档后，可以得到一个明确结论：

**Holo 不应该变成任何现成框架的 wrapper。Holo 应该吸收这些框架已经验证过的工程原则，落成一个 host-owned、LLM-driven、tool-coupled、memory-aware、graph-observable 的通用 agent kernel。**

金融仍然是当前最重要的能力验证场，因为金融任务同时压测检索、证据、口径消歧、表格、单位、公式、引用、数值验证、成本和最终合成。但金融能力不应该写成金融规则脚本。正确路线是：

```text
通用 AgentGraph Runtime
  + 标准 Tool Protocol
  + 可管理 Memory / Cache
  + 领域 Domain Pack
  + Verifier-as-tool
  + Benchmark / UI / Telemetry
```

其中 finance pack 只是第一个高压 domain pack。未来数学、物理、代码、研究、文件工作、role play 和长期常驻任务，都应该共享同一套 agent loop。

Holo 的硬不变量仍然成立：

- LLM 负责语义判断、计划、slot binding、证据取舍、答案合成。
- Host 负责 schema、权限、工具执行、日志、验证、成本、cache、memory、停止边界。
- Gold/reference 只用于 post-run scoring，不能进入 runtime。
- 禁止答案表、关键词拦截、阈值捷径、host 代替模型选择金融事实或最终数字。

---

## 1. 本次审阅材料

### 1.1 外部框架

本地参考仓库位于 `/tmp/holo_agent_framework_refs`：

| 框架 | 本地路径 | 官方来源 | 对 Holo 的主要价值 |
| --- | --- | --- | --- |
| LangChain | `/tmp/holo_agent_framework_refs/langchain` | <https://github.com/langchain-ai/langchain> | 统一模型、工具、检索器、文档、集成与观测接口 |
| LangGraph | `/tmp/holo_agent_framework_refs/langgraph` | <https://github.com/langchain-ai/langgraph> | 长任务 state graph、checkpoint、stream、interrupt、memory |
| Semantic Kernel / MAF | `/tmp/holo_agent_framework_refs/semantic-kernel` | <https://github.com/microsoft/semantic-kernel> | kernel/service/plugin/function/process/filter 分层治理 |
| Hermes Function Calling | `/tmp/holo_agent_framework_refs/hermes-function-calling` | <https://github.com/NousResearch/Hermes-Function-Calling> | schema tool call、tool response、recursive tool loop |
| HERMES Math Agent | `/tmp/holo_agent_framework_refs/hermes-math-agent` | <https://github.com/aziksh-ospanov/HERMES> | verifier-as-tool、单步验证、已验证声明记忆 |

### 1.2 Holo 内部文档

重点复核的本地文档：

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

## 2. 回看 Holo 开发过程后的真实主线

### 2.1 从对话系统走向 host-owned harness

早期 Holo 更像带记忆和 transport 的对话系统。Kernel v3 后，真正核心变成：

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

这条主线和 LangGraph、Semantic Kernel、Hermes 的结论一致：模型可以提出计划和工具调用，但执行权、权限、审计、状态恢复和停止边界必须由 host 拥有。

### 2.2 从一次性回答走向证据耦合的问题解决

金融题暴露了普通 chat 模型最明显的弱点：

- 找错报表。
- 拿错期间。
- 混淆 revenue、net revenue、operating revenue、total revenue and other income。
- 单位和 scale 错误。
- 把公式中间量和最终量混掉。
- 最终答案看似合理但引用不支持。

因此 Holo 逐步形成了 finance fact ledger、slot frame、FormulaTrace、numeric verifier、citation support、synthesis gate 和 benchmark failure taxonomy。这说明当前金融能力的目标不是“背答案”，而是：

```text
source-grounded financial reasoning workflow
```

### 2.3 从被动 RAG 走向可管理工作上下文

`KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md` 已经给出关键判断：naive top-k RAG 不够。Holo 需要的是 agent memory：

- event memory：journal 是事实序列。
- thread working set：当前目标、缺口、成功发现、失败尝试。
- durable memory：经 host 审批的用户、项目、任务记忆。
- research graph：query、source、document、evidence、claim 的关系。
- tool memory：工具失败、来源质量、抓取和解析失败经验。
- reflection memory：最终答案或失败后的可复用经验。

这与 LangGraph 的 memory/checkpoint、HERMES 的 verified-claim memory、MemGPT 风格的 virtual context 都是一条路线：让模型看到正确的工作上下文，而不是把所有历史原文塞进 prompt。

### 2.4 从演示事件列表走向真实 runtime graph

最近 dashboard 的问题很典型：graph 跳动、complete 后仍变动、节点突然一次性导通、UI 和真实 loop 不同步。根因不是 CSS，而是 UI 订阅的不是严格 typed runtime state delta。

下一步必须把 agent loop 显式化为 graph runtime。UI 只渲染真实事件：

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

finalized 后当前 turn graph 冻结。后续异步统计、memory proposal 或 report update 必须进入 post-run 区域，不能继续污染本 turn 的 running 状态。

---

## 3. 各框架具体可以参考什么

### 3.1 LangChain：参考组件接口和生态，不接管 Holo loop

LangChain 的价值在于组件标准化和生态，而不是让 Holo 变成 LangChain Agent。

Holo 应吸收：

- `ModelClient`、embedding、reranker、structured output 的统一接口。
- Tool、Retriever、Document、Loader、Splitter、VectorStore 的标准边界。
- callback / tracing / usage 的观测思想。
- 第三方 connector 的适配方式。

落到 Holo：

- `kernel_v3/processors` 继续作为 provider-agnostic processor fabric。
- `kernel_v3/retrieval` 明确区分 provider、loader、extractor、ranker、evidence reducer。
- finance、math、physics、code、workspace、browser 做成 domain/tool pack。
- 每个 pack 提供工具、上下文模板、验证器、prompt contract，不替模型决定答案。

不应照搬：

- 不用 LangChain Agent 替代 `LoopControllerV3` 或未来 `AgentGraphRuntime`。
- 不用文本 callback 替代 typed journal。
- 不把生态便利性置于 host-owned invariant 之上。

### 3.2 LangGraph：下一阶段最重要的 runtime 参考

LangGraph 的核心是 stateful agent runtime，而不是“画流程图”。Holo 当前已经有 journal、taskgraph、workloop 和 dashboard，但仍偏线性 loop。下一步应升级为 typed graph runtime。

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

应吸收：

- checkpoint / resume / replay：常驻任务和长金融研究需要恢复。
- stream state delta：UI、benchmark、debugger 同源订阅。
- interrupt：证据不足、权限、成本、用户确认时暂停。
- branch / join：检索、候选事实、候选公式、验证器并行。
- memory integration：thread working set 和 durable memory 成为 state 的一部分。

禁止事项：

- 不用 graph edge 写关键词规则。
- 不让 host edge 条件决定哪个金融数字是最终答案。
- 不为了 demo 画假 topology。graph 必须来自真实 runtime state。

### 3.3 Semantic Kernel / Microsoft Agent Framework：参考分层治理

Semantic Kernel / Microsoft Agent Framework 的价值是企业级工程分层。

Holo 可以映射为：

```text
HoloKernel
  services:
    model providers
    memory
    retrieval
    journal
    telemetry
    artifact store
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
    long-running AgentGraph
    benchmark process
    research process
  filters:
    policy
    schema validation
    provenance validation
    cache accounting
    cost guard
    citation check
    numeric verifier
```

这个分层可以把 Holo 旧有概念落到更硬的工程实体上：

| 旧概念 | Kernel v3 落点 |
| --- | --- |
| Perception Bus | event intake / observation reducer |
| Action Market | tool registry / planner-proposed tool call |
| Memory Fabric | memory layers / working set / durable store |
| Consciousness Ledger | journal + checkpoint + replay |
| Processor Fabric | graph nodes / plugins / process steps |

不应照搬：

- 不引入过重企业模板，避免拖慢当前高压迭代。
- 不把 plugin 写成规则路由系统。
- 不用多 agent 概念掩盖当前最重要的单 agent loop 质量。

### 3.4 Hermes Function Calling：彻底标准化工具闭环

Hermes Function Calling 给出的核心很朴素，但对 Holo 至关重要：

```text
model proposes tool_call
host parses and validates schema
host checks policy
host executes allowed function
host returns tool_response or tool_error
model observes and continues or finalizes
```

Holo 应固化：

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
  usage,
  errors
}
```

落地要求：

- 错误也作为 observation 交回模型，不让 loop 卡死。
- 简单任务允许模型选择不调用工具直接回答。
- 复杂任务允许模型多轮工具调用，但必须有预算和停止状态。
- tool schema、tool result schema、journal schema 三者统一。

禁止事项：

- 不暴露未授权工具。
- 不让 host 猜测模型想调用什么。
- 不让工具返回大段不可控原文污染 prompt，原文进入 artifact，prompt 只进 compact observation。

### 3.5 HERMES Math Agent：把 verifier 做成工具，而不是 host 代替模型

HERMES Math Agent 的关键思想是 verifier-as-tool。Verifier 不替模型思考，而是在关键 claim 处给出形式化或半形式化反馈。

Holo 可以吸收：

- 金融：numeric verifier、unit checker、citation verifier、formula trace checker、answer cleanliness verifier。
- 数学：SymPy、Lean、CAS、数值采样、反例搜索。
- 物理：单位维度检查、公式库、仿真器、边界条件检查。
- 代码：test runner、type checker、lint、static analyzer。

关键是模型主动使用 verifier，或在 host 要求的 final gate 中看到 verifier 反馈后修复。Host 不做语义答案选择，只确保 verifier 输入输出结构合规、证据链可审计。

---

## 4. Holo 当前最应该参考并落地的 8 个方向

### 4.1 AgentGraph Runtime v0

目标：把现在的线性 loop 和后验 journal，升级为真实的 typed state graph。

最小落地：

- `AgentGraphState`
- `AgentNodeEvent`
- `AgentEdgeEvent`
- `GraphDeltaStream`
- `checkpoint_id`
- `finalized_at`

收益：

- UI 实时性明显改善。
- complete 后 graph 不再跳动。
- benchmark 可以按节点统计失败、耗时和成本。
- 单题内部并行化有明确载体。

### 4.2 Tool Protocol v1

目标：所有工具都走同一接口，不再因金融、检索、memory、calculator 各自为政导致调试困难。

最小落地：

- `ToolManifest`
- `ToolCall`
- `ToolResult`
- `ToolError`
- `Observation`

收益：

- LLM 可以稳定理解工具可用性。
- Host 可以统一权限、成本、日志、错误恢复。
- Hermes 风格递归 tool loop 成为通用能力。

### 4.3 Finance Domain Pack v2

目标：把金融能力做成 domain pack，而不是 runtime 中散落的特殊分支。

Pack 内容：

- finance-specific prompt contract
- SEC / EDGAR / companyfacts tools
- filing document acquisition
- finance fact ledger
- slot binding packet
- FormulaTrace
- calculator
- numeric/citation/unit verifier
- benchmark profile

边界：

- Slot binding 由 LLM 做。
- Metric/period/fact 选择由 LLM 做。
- Host 暴露候选、执行计算、验证引用和数值支持。
- Host 不靠关键词/阈值决定答案。

### 4.4 Parallel Workbench

目标：把“并行跑题”扩展为“单题内部并行”。

可并行部分：

- SEC companyfacts、filing text、local source directory、web retrieval。
- metric 候选、period 候选、document 候选。
- calculator candidate trace。
- numeric/citation/unit/cleanliness verifier。

合并方式：

- Host 聚合候选和验证结果。
- LLM adjudicator 选择最合理的事实和最终答案。
- Host 只做 schema、provenance、budget 和 audit。

### 4.5 Memory / Cache / Context Page-In

目标：降低成本，提高稳定性，让长期任务不从零开始。

落地：

- Stable prompt prefix 前置。
- 动态 user/evidence/context 后置。
- Thread working set page-in。
- Tool failure memory。
- Verified claim memory。
- Finance error reflection memory。
- Cache hit / miss 进入 report。

注意：

- Memory 不能泄露 holdout gold。
- 反思只能存 workflow lesson、failure mode、source family、tool strategy，不能存答案表。
- Cache 优化不能通过固定答案模板作弊。

### 4.6 Verifier-as-tool 全局化

目标：把金融 verifier 经验迁移到数学、物理、代码、研究。

落地：

- 每个 domain pack 注册 verifier tools。
- Planner 可以主动调用 verifier。
- FinalGate 可以要求模型在 verifier feedback 后修复。
- Benchmark 记录 verifier coverage、verifier pass rate、verifier repair success。

### 4.7 Benchmark and Post-Run Analytics

目标：论文和报告需要统计，不是单题 anecdote。

必须严格区分：

- FB debug/system-tuning split。
- FB holdout/evaluation split。
- FAB dev10。
- FAB public no-gold behavior run。
- Holo workflow challenge no-gold stress run。

每次报告至少包含：

- item_count
- pass_rate / numeric_accuracy
- workflow_score / substrate_score
- calculator_used_rate
- formula_trace_present_rate
- citation_present_rate
- processor_call_count
- prompt_cache_hit_ratio
- average_total_tokens
- failure taxonomy

禁止：

- 把 debug 分数当 holdout 分数。
- 把 no-gold 行为集说成准确率。
- 把 fake/oracle control 说成 live ability。

### 4.8 Demo UI 作为真实调试器

目标：演示 UI 不只是好看，而是调试工具。

UI 应展示：

- 右侧主 chat：用户输入、最终答复、流式状态。
- 左侧/中部 graph：真实 agent graph state。
- 大 console：结构化模型输出、tool call、observation、verifier feedback。
- Thread selector、clear、new thread、run freeze。
- Case gallery：稳定可解的金融问题。

原则：

- UI 不生成 fake graph。
- Graph 节点状态来自 runtime delta。
- finalized 后本 turn 不再改变。
- post-run memory/report/statistics 放到独立区域。

---

## 5. 对当前金融能力的解释口径

当前 Holo 最强的可解释能力是：

```text
source-grounded financial fact extraction
+ metric/period/unit disambiguation
+ formula-backed calculation
+ citation/numeric verification
+ auditable agent trace
```

它能比较稳定展示的题型：

- 单点财报事实抽取。
- 财务指标口径消歧。
- 原始 filing / companyfacts 取证。
- turnover、margin、DIO、growth、capital intensity 等多步计算。
- 不可得或未单独披露判断。
- 部分交易、估值、adjusted metric bridge。

它当前仍不够稳定的题型：

- 复杂长文档多表跨页定位。
- source acquisition 很难的 FinanceBench doc retrieval。
- 需要多假设建模和行业判断的 DCF/LBO 类问题。
- 模型 JSON 失效后无法顺利进入 calculator 的题。
- final synthesis 自行引入无来源阈值或行业常识数字的题。

这不是说明 Holo 方向错，而是说明下一轮瓶颈在：

- 单题内部并行检索。
- LLM-owned slot binding 稳定性。
- FormulaTrace 和 citation support 更强地进入 synthesis。
- Verifier feedback 更自然地触发 model repair。
- Processor cache 和 context page-in 降成本。

---

## 6. 对通用能力的解释口径

Holo 的通用能力不是另起一套系统。金融 agent loop 的底层结构本来就是通用的：

| 通用问题求解要素 | 金融中的体现 | 数学/物理/代码中的对应 |
| --- | --- | --- |
| 目标理解 | task.compile | theorem/problem spec/issue spec |
| Slot binding | company, metric, period, unit | variables, assumptions, files, APIs |
| Evidence | filing facts, citations | lemmas, formulas, logs, docs |
| Transform | formulas, ratios | algebra, simulation, code patch |
| Tool use | retrieval, calculator | CAS, Lean, test runner |
| Verification | numeric/citation gate | proof check, unit check, tests |
| Synthesis | finance answer | proof/explanation/fix summary |
| Memory | source/tool/failure lessons | reusable proof patterns/project conventions |

因此通用能力路线是：

```text
AgentGraph Runtime + Tool Protocol + Memory + Verifier-as-tool
```

Finance pack 先跑通后，math pack、physics pack、code pack、research pack 只是换工具、prompt contract 和 verifier，不应该重写 agent loop。

---

## 7. 下一轮工程路线

### P0：Graph delta 和 final freeze

完成标准 `AgentGraphDelta`，让 runtime、UI、benchmark 使用同一事件源。解决 UI 延迟、complete 后仍 running、graph 跳动的问题。

### P1：Tool Protocol v1

把 retrieval、calculator、memory、verifier、workspace 等统一成 manifest/call/result/error/observation。

### P2：Finance live ability rerun

在 slot_bind、synthesizer repair、formula support、processor usage 已补强后，按 split policy 跑：

- FB debug offsets `0-9` 小规模确认。
- FB holdout offsets `10-149` 分批。
- FAB dev10。
- FAB public behavior run。

### P3：Single-item internal parallelism

实现 retrieval branches、candidate branches、verifier branches 的 branch/join。先从 FinanceBench doc retrieval 入手，因为它最需要并行 source acquisition。

### P4：Memory/cache productization

建立 thread working set、verified claim memory、tool failure memory，稳定 prompt prefix，按 provider usage 统计 cache 命中。

### P5：Paper/report analytics

每次 run 自动生成：

- capability table
- failure taxonomy
- cost/cache profile
- workflow coverage
- debug vs holdout split
- representative trace excerpt

---

## 8. 可直接用于讲稿的表述

Holo Kernel v3 的定位不是又一个 LangChain app。我们参考了 LangChain 的组件生态、LangGraph 的状态图 runtime、Semantic Kernel 的 kernel/plugin/process/filter 分层、Hermes 的结构化工具调用，以及 HERMES Math Agent 的 verifier-as-tool 思路，但 Holo 的核心保持不变：模型做语义判断，host 做执行、验证、审计、记忆和边界。

金融是当前主战场，因为金融题是一个非常严苛的综合能力测试：它要求系统找到正确来源、识别正确口径、处理单位和期间、调用计算工具、给出引用、并验证最终数值。Holo 当前已经具备可审计的金融问题解决链路，下一步不是写更多规则，而是把 agent loop 升级为真实的 typed graph runtime，并让检索、候选事实、验证器和合成更加并行、稳定、低成本。

这几个月没有白干的证据不是某个单点 demo，而是系统形态已经成型：processor fabric、tool loop、retrieval workbench、finance ledger、FormulaTrace、numeric verifier、memory pipeline、benchmark report 和 dashboard 都已经存在。接下来要做的是把这些部件从线性流程整合成统一的 AgentGraph Kernel。

---

## 9. 一句话路线图

```text
不要把 Holo 包成 LangChain。
把 Holo 做成自己的 AgentGraph Kernel。

LangChain 给接口生态。
LangGraph 给状态图运行时。
Semantic Kernel 给分层治理。
Hermes 给工具调用闭环。
HERMES Math Agent 给 verifier-as-tool。

Holo 的核心竞争力：
LLM 语义智能 + Host 执行验证 + 工具链 + 记忆 + 可视化 + 金融高压验证。
```

