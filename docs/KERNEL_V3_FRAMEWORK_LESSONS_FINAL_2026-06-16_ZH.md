# Holo Kernel v3 开源框架审阅与开发过程复盘总成

日期：2026-06-16  
分支：`kernel-v3`  
用途：报告/论文方法章节、讲稿、下一阶段工程路线、项目交接  
状态：最终可引用总成文档。本文件合并并裁剪此前多份框架审阅草稿；后续汇报优先引用本文。

---

## 0. 一句话结论

Holo Kernel v3 不应该变成 LangChain、LangGraph、Semantic Kernel 或 Hermes 的 wrapper。它应该吸收这些框架已经验证过的工程原则，继续落成一个 **host-owned、LLM-driven、tool-coupled、memory-aware、graph-observable** 的通用 agent kernel。

金融是当前最重要的压力测试场景，因为金融题同时压测检索、证据、表格、口径、单位、公式、引用、验证、成本和最终合成。但金融能力不能写成金融规则脚本。正确路线是：

```text
Generic AgentGraph Runtime
  + Standard Tool Protocol
  + Processor / Provider Fabric
  + Durable Memory / Working Set / Research Graph
  + Domain Packs
  + Verifier-as-tool
  + Benchmark / Telemetry / UI
```

finance pack 是第一个高压 domain pack。未来数学、物理、代码、研究、文件工作、role play 和系统常驻任务，都应该共享同一套 agent loop。

---

## 1. 本次审阅对象

### 1.1 外部框架与官方机制参考

| 框架 | 本地参考路径 | 官方来源 | 对 Holo 的主要价值 |
| --- | --- | --- | --- |
| LangChain | `/tmp/holo_agent_framework_refs/langchain` | <https://docs.langchain.com/oss/python/langchain/overview> | 统一 model、tool、retriever、document、structured output、middleware、observability 接口 |
| LangGraph | `/tmp/holo_agent_framework_refs/langgraph` | <https://docs.langchain.com/oss/python/langgraph/overview> | state graph、durable execution、checkpoint/resume、streaming、interrupt、memory、branch/join |
| Semantic Kernel / Microsoft Agent Framework | `/tmp/holo_agent_framework_refs/semantic-kernel` | <https://learn.microsoft.com/en-us/semantic-kernel/overview/> | kernel/service/plugin/function/process/filter 的工程分层和企业治理 |
| Hermes Function Calling | `/tmp/holo_agent_framework_refs/hermes-function-calling` | <https://github.com/NousResearch/Hermes-Function-Calling> | schema tool call、tool response、recursive observation loop、JSON mode |
| HERMES Math Agent | `/tmp/holo_agent_framework_refs/hermes-math-agent` | <https://github.com/aziksh-ospanov/HERMES> | verifier-as-tool、formal verifier、verified-claim memory、agent/verifier coupling |
| DeepSeek Context Caching | N/A | <https://api-docs.deepseek.com/guides/kv_cache> | stable prefix、cache hit/miss telemetry、long-context cost discipline |

### 1.2 Holo 内部文档

重点复核的开发过程文档：

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

这些文档共同说明：Kernel v3 的主线不是临时刷题脚本，而是从对话、记忆、工具、检索、金融基准、可视化逐步收敛为一个 host-owned agent harness。

---

## 2. Kernel v3 必须坚持的硬不变量

| 领域 | LLM 负责 | Host 负责 |
| --- | --- | --- |
| 任务理解 | 判断用户目标、领域、难度、是否需要工具 | 提供任务 profile、上下文边界、可用工具清单 |
| 计划 | 提出下一步行动、选择工具、判断是否继续 | 校验 action schema、权限、预算、停止边界 |
| 金融事实 | 进行 metric/period/company/unit 的语义绑定 | 抽取候选事实、保留 provenance、记录 fact ledger |
| 计算 | 选择公式意图、解释计算结果 | 执行 calculator、记录 FormulaTrace、返回 observation |
| 验证 | 决定是否修正、继续检索、重新计算、最终回答 | 执行 verifier、记录 issue、检查引用和数值支持 |
| 记忆 | 提出可复用经验或需 recall 的记忆 | 审批、写入、隐私、TTL、provenance、删除 |
| 评测 | 产出真实答案和 trace | post-run scoring、split 管理、报告统计 |

禁止事项：

- 禁止 benchmark gold/reference 进入 runtime prompt、retrieval context、tool context、memory。
- 禁止答案表、关键词拦截、阈值捷径。
- 禁止 host 不经 LLM slot binding 自己选择 row、metric、period、公式和最终答案。
- 禁止为了 demo 伪造 topology 或后验拼接实时事件。
- 禁止把 debug split 和 holdout split 混在一起报分。

---

## 3. 外部框架可以参考什么

### 3.1 LangChain：参考接口生态，不接管核心 loop

LangChain 的价值在于标准组件和生态适配。它提醒我们：复杂 agent 的底层接口必须稳定，否则每次换 provider、检索器、向量库、工具都会污染主 loop。

Holo 应吸收：

- `ModelClient`、embedding、reranker、structured output 的统一接口。
- `Tool`、`Retriever`、`Document`、`Loader`、`Splitter`、`VectorStore` 的清晰边界。
- middleware / tracing / usage 的观测思想。
- 第三方 connector 适配层，避免重复造所有外部工具。

落到 Holo：

- `kernel_v3/processors` 继续作为 provider-agnostic processor fabric。
- `kernel_v3/tools.py` 应稳定成 tool manifest / call / result 协议。
- `kernel_v3/retrieval` 明确区分 provider、loader、extractor、ranker、evidence reducer。
- finance、math、physics、code、workspace、browser 应成为 domain/tool pack。

不应照搬：

- 不用 LangChain Agent 替代 Holo 的 host-owned loop。
- 不用文本 callback 替代 typed journal。
- 不为了集成便利牺牲权限、审计、防泄漏和 benchmark 边界。

### 3.2 LangGraph：下一阶段最重要的 runtime 参考

LangGraph 的核心不是“画图”，而是让 agent 成为显式、可恢复、可流式观察的状态机。Kernel v3 目前已有 journal、taskgraph、runtime graph projection 和 dashboard，但真实执行仍偏线性 loop。下一步应升级为 typed graph runtime。

Holo 应吸收：

- `StateGraph`：每个节点读写 typed state。
- durable execution：任务失败、中断后可恢复。
- checkpoint / replay：长任务和夜间 benchmark 可以复现。
- streaming state delta：UI、CLI、benchmark report 订阅同源 delta。
- interrupt / human-in-the-loop：证据不足、权限、成本或歧义时暂停。
- branch / join：并行检索、并行候选事实、并行公式和验证器。
- memory/store：thread working set 和 durable memory 成为 state 的一部分。

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
- 不让 host edge 条件决定哪个金融数字是答案。
- 不为了 UI 画假 topology。UI 只能渲染真实 runtime state。

### 3.3 Semantic Kernel / Microsoft Agent Framework：参考分层治理

Semantic Kernel / Microsoft Agent Framework 的价值是工程组织方式：kernel 管服务，plugin 管能力，function 管可调用单元，process 管长流程，filter 管前后置治理。

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

这能把旧阶段里的概念落成更硬的工程抽象：

| 旧概念 | Kernel v3 落点 |
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

### 3.4 Hermes Function Calling：把工具协议彻底标准化

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
  cost_usage,
  cache_status
}
```

关键要求：

- 工具调用必须结构化，不能从自然语言里猜。
- Host 可以拒绝 schema 错误、权限错误、危险副作用。
- 错误也是 observation，应反馈给模型继续判断。
- 工具数量和上下文要按 task profile 暴露，不要把所有工具一次性塞给所有任务。
- 简单问候、普通闲聊和无需工具的任务必须允许模型直接回答，不能默认拖进长 agent loop。

### 3.5 HERMES Math Agent：把 verifier 做成模型可调用工具

HERMES Math Agent 最值得 Holo 吸收的点是 verifier-as-tool：

- 模型遇到关键数学声明时主动调用 verifier。
- 验证器返回 correct / incorrect / inconclusive。
- 验证过的声明可以进入记忆，供后续证明复用。
- agent loop 仍由模型推进，验证器不是 host 替模型思考。

Holo 对应落点：

- 金融里将 `finance.verify_numeric` 暴露为标准 read-only tool。
- 数学可以接入 CAS、Lean、SymPy、Z3 或专用 verifier。
- 物理可以接入量纲检查、单位换算、符号推导、数值仿真。
- 代码可以接入 tests、type checker、static analyzer、runtime sandbox。

关键边界：

- Verifier 只验证声明或计算链，不替模型选择最终语义答案。
- Host 只负责调用、记录、校验工具输出。
- 模型继续决定是否修正、继续检索、重新计算或最终回答。

### 3.6 DeepSeek Context Caching：把 cache 当成系统能力

DeepSeek 的 context caching 不是 agent 框架，但它直接影响 Kernel v3 的运行成本、速度和长上下文可行性。官方机制强调：后续请求只有完整复用已持久化的 prefix unit 才会命中 cache，响应 usage 中会给出 `prompt_cache_hit_tokens` 与 `prompt_cache_miss_tokens`。

Holo 应吸收：

- stable prefix 前置：系统 contract、tool manifest、domain policy、schema、少变的 source policy。
- dynamic packet 后置：当前 question、observation、facts、gaps、trace。
- 大文档和长 evidence 用 refs、support index、summary，不反复塞全量原文。
- benchmark report 按 processor/task type 统计 cache hit ratio。
- cache 优化必须服务真实解题能力，不能把 gold、答案表或不可泛化提示塞进 prefix。

落到 Holo：

- `kernel_v3/processors/usage.py` 汇总 provider usage 和 prompt cache。
- `docs/KERNEL_V3_PROGRESS_2026-06-16_PROCESSOR_USAGE_CACHE_METRICS.md` 记录了 processor cache 指标。
- `finance_working_state`、`toolchain_state`、support index 应保持 compact、稳定和可复用。

---

## 4. Holo 开发过程复盘

### 4.1 从对话系统走向 host-owned harness

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

这和 LangGraph、Semantic Kernel、Hermes 的共同结论一致：模型可以提出计划和工具调用，但执行权、权限、审计、状态恢复和停止边界必须由 host 拥有。

### 4.2 从一次性回答走向证据耦合的问题解决

金融题暴露了普通 chat 模型最明显的弱点：

- 找错报表。
- 拿错期间。
- 混淆 revenue、net revenue、operating revenue、total revenues and other income。
- 单位和 scale 错误。
- 把公式中间量和最终量混掉。
- 最终答案看似合理但引用不支持。

因此 Holo 逐步形成了 finance fact ledger、slot frame、FormulaTrace、numeric verifier、citation support、synthesis gate 和 benchmark failure taxonomy。当前金融能力的目标不是“背答案”，而是：

```text
source-grounded financial reasoning workflow
```

### 4.3 从被动 RAG 走向可管理工作上下文

`KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md` 已经给出关键判断：naive top-k RAG 不够。Holo 需要的是 agent memory：

- event memory：journal 是事实序列。
- thread working set：当前目标、缺口、成功发现、失败尝试。
- durable memory：经 host 审批的用户、项目、任务记忆。
- research graph：query、source、document、evidence、claim 的关系。
- tool memory：工具失败、来源质量、抓取和解析失败经验。
- reflection memory：最终答案或失败后的可复用经验。

这与 LangGraph persistence/store、HERMES verified-claim memory、MemGPT virtual context 是一条路线：让模型看到正确的工作上下文，而不是把所有历史原文塞进 prompt。

### 4.4 从演示事件列表走向真实 runtime graph

dashboard 曾经出现 graph 跳动、complete 后仍变动、节点突然一次性导通、UI 和真实 loop 不同步。根因不是 CSS，而是 UI 订阅的不是严格 typed runtime state delta。

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

### 4.5 从能力展示走向统计闭环

当前本地金融题库不是一个单一集合，而是多个任务族：

| Track | Path | Count | Gold/annotation | 用途 |
| --- | --- | ---: | --- | --- |
| FB / FinanceBench doc retrieval | `data/bench/finance/financebench_doc_retrieval.jsonl` | 150 | 有 gold/sidecar | 主大型金融 benchmark |
| FAB v2 public | `data/bench/finance/fabv2_public.jsonl` | 27 | 无公开 gold | public behavior/substrate/cost/failure taxonomy |
| FAB dev10 | `data/bench/finance/fabv2_dev10.jsonl` | 10 | 有 gold/annotation | 小型开发调试集 |
| Holo workflow challenge | `data/bench/finance/holo_finance_workflow_challenge.jsonl` | 50 | 无 gold | workflow stress/demo challenge |

报告时必须区分：

- debug / holdout / public / no-gold。
- FB 与 FAB。
- answer accuracy 与 workflow/substrate/cost/failure taxonomy。
- live 结果与 fake/oracle harness test。

---

## 5. 当前已落地的工程吸收点

| 方向 | 已有落点 | 价值 |
| --- | --- | --- |
| Host-owned loop | `kernel_v3/agent/runtime.py`, `kernel_v3/loop.py`, `PolicyGate`, `ToolRegistry` | 模型提议，host 执行和记录 |
| Processor fabric | `kernel_v3/processors/` | schema-first model packet、usage、JSON repair、provider abstraction |
| Tool protocol | `kernel_v3/tools.py` | schema validation、permission、read-only/side-effect boundary |
| Retrieval workbench | `kernel_v3/retrieval/` | search/fetch/extract/evidence/source quality/workbench judgment |
| Finance domain pack | `kernel_v3/finance/` | fact ledger、target binding、calculator、numeric verifier、synthesis support |
| Verifier-as-tool | `finance.verify_numeric` | planner 可主动调用标准验证工具 |
| Runtime graph projection | `kernel_v3/runtime_graph.py` | dashboard/CLI 可订阅 typed graph delta 的雏形 |
| Benchmark observability | `kernel_v3/bench/finance.py`, `kernel_v3/bench/report.py` | cache、processor、formula support、failure layer、verifier tool usage 统计 |
| Memory/RAG substrate | `kernel_v3/memory/`, memory/RAG research docs | durable memory、working set、research graph、reflection proposal |
| UI demo | `kernel_v3/demo_dashboard.py` | chat、runtime console、topology、prompt bank、case selector |

近期新增观测能力：

- processor prompt cache hit/miss tokens 与 cache hit ratio。
- processor task type / provider model / status / error counts。
- FormulaTrace support index 与 coverage metrics。
- `finance.verify_numeric` tool call/use/error metrics。
- agent loop stage coverage、terminal rate、tool/search/verify/answer stage presence。
- post-final clean rate、toolchain depth、tool action repetition/error metrics。

这些能力都属于观测、压缩和验证层，不参与答案选择，不改变 LLM-owned financial reasoning。

---

## 6. 为什么 Holo 目前只能攻克一部分题

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

## 7. Kernel v3.1 应落成什么

### 7.1 AgentGraph Runtime

目标：把当前线性 workloop 升级为 typed graph runtime。

优先级最高的工程动作：

1. 定义 `AgentGraphState`、`AgentGraphNode`、`AgentGraphEdge`、`AgentGraphDelta`。
2. 每个节点输出 typed delta，而不是事后从 journal 猜图。
3. Dashboard、CLI、benchmark report 全部订阅同源 delta。
4. 当前 turn `finalized` 后冻结图，post-run diagnostics 进入独立区域。
5. 支持 branch/join，为并行检索和并行候选验证准备接口。

### 7.2 Standard Tool Protocol

目标：所有工具对 planner 看起来一致。

下一步：

1. 统一 `ToolManifest` 字段：schema、side effect、cost、authority、streaming、domain tags。
2. 统一 `ToolCall` 字段：purpose、expected observation、call id、node ref。
3. 统一 `ToolResult` 字段：status、observation、citations、artifacts、diagnostics、retryable、cache status。
4. 工具错误回到模型作为 observation，而不是 host 私下吞掉。
5. 允许 domain pack 提供 tool templates，但禁止 tool templates 变成答案规则。

### 7.3 Domain Pack

目标：金融、数学、物理、代码、研究共享通用 loop，只换工具和上下文。

每个 domain pack 应提供：

- capability manifest。
- tool manifest。
- context compiler。
- prompt contract。
- verifier tools。
- benchmark/eval profile。
- failure taxonomy。
- memory extraction policy。

Finance pack 当前是第一个成熟样板。后续 math pack 可以从 `calculator.compute`、symbolic algebra、proof verifier 开始；physics pack 可以从 unit/dimension checker、formula library、simulation sandbox 开始；code pack 可以从 tests/typecheck/static analysis 开始。

### 7.4 Working State / Context / Cache

目标：既提高能力，也控制成本。

Holo 需要三个同时成立：

- 正确上下文：模型看到当前任务需要的 working set、facts、gaps、tool history。
- 稳定前缀：processor prompt stable prefix 固化，提高 provider prompt cache 命中率。
- 可压缩动态区：大文档、长 trace、重复 evidence 用 refs、summaries、support index，而不是全量原文。

建议 packet：

```text
toolchain_state:
  recent tool calls
  recent observations
  failed tools
  repeated actions
  terminal/post-final state
  model attention hints

finance_working_state:
  slot frame
  compact finance facts
  formula traces
  numeric verifier result
  missing slots/gaps
  citation/evidence refs
```

边界：

- packet 只暴露已有状态和缺口。
- packet 不决定答案。
- packet 不读取 gold。
- packet 不用关键词/阈值选择金融事实。

### 7.5 Verifier-as-tool

金融里的正确形态：

```text
LLM identifies target claim / formula / numeric answer
-> calls finance.verify_numeric with facts, traces, citations, evidence
-> observes passed/failed/issues
-> repairs, searches more, recalculates, or finalizes
```

下一步：

- 让 planner 更自然地选择 `retrieval.run -> calculator.compute -> finance.verify_numeric -> respond`。
- 将 verifier issue codes 变成模型可读的 repair hints。
- 对数学/物理/代码复用同一 verifier-as-tool 模式。

### 7.6 Agent-loop 并行化

题目级并行已经可用。下一步是单题内部并行：

```text
Planner proposes N evidence hypotheses
Host runs retrieval branches in parallel
ObservationReducer compresses each branch
LLM/workbench compares source authority and coverage
Verifier checks selected claim/formula
Synthesizer answers
```

适合并行的分支：

- SEC companyfacts vs filing text vs investor relations PDF。
- metric alias candidates。
- period candidates。
- formula input candidates。
- source-family candidates。
- verifier / counterexample candidates。

边界：

- 并行化不能变成 host 替模型选答案。
- Host 可以并行执行候选工具调用、压缩观察、统计成本。
- LLM 负责根据观察选择下一步和最终语义答案。

### 7.7 Benchmark / Telemetry

每次多题 run 必须报告：

- dataset / split / item_count。
- pass_rate / numeric_accuracy。
- workflow_score / substrate_score。
- citation_present_rate。
- calculator_used_rate / formula_trace_present_rate。
- finance_verify_numeric_tool_used_rate。
- processor_prompt_cache_hit_ratio。
- processor_task_type_counts。
- toolchain_depth / repeated_action_rate / tool_error_rate。
- agent_loop_stage_coverage_rate。
- failure_layer_counts。

对无 gold 集合，不报告 accuracy，只报告 workflow/substrate/cost/failure。

### 7.8 UI / Observability

目标：展示真实 agent loop，而不是把 ChatGPT 包一层皮。

UI 应展示：

- chat 输入输出。
- runtime console：模型 packet、工具调用、observation、verifier、final/failure。
- graph topology：节点、边、branch/join、active state。
- per-node timing/cost/cache。
- evidence/facts/formula/citations 的结构化链接。
- current turn 和 post-run 区域严格分离。

不要展示：

- 假 topology。
- 后验拼接成“看起来像实时”的事件。
- 过长原始文本导致 UI 失焦。
- 模型私有 hidden chain-of-thought 原文作为产品依赖。应展示 public trace、模型显式计划、工具调用、观察、结构化理由和状态变化。

---

## 8. 对通用能力的意义

Kernel v3 的目标不只是金融。金融是压力测试，通用 agent loop 才是主体。

Holo 应擅长：

- 普通问答和轻量 chat：模型能直接回答，不陷入不必要长 loop。
- 文件/代码/研究工作：临时组装工具链完成任务。
- 领域研究：根据 domain pack 暴露合适工具、source policy、verifier。
- 长期常驻任务：任务中断、恢复、记忆、提醒、后续行动。
- role play 和互动：保持 thread state，不破坏安全/权限边界。
- 数学/物理/证明：用 verifier 工具增强可靠性。
- 金融分析：检索、口径、计算、验证、引用、报告。

通用能力与金融能力的共通性：

- 都需要任务理解、slot binding、工具选择、证据组织、变换计算、验证和合成。
- 都需要 working memory 和 durable memory。
- 都需要成本/cache 控制。
- 都需要可观测 trace。

区别：

- 金融更依赖外部权威来源、口径、期间、单位和引用。
- 数学/物理更依赖形式验证、量纲、符号推导。
- 代码更依赖文件系统、测试、类型检查和运行时反馈。
- role play 更依赖长期偏好、风格和关系连续性。

因此 Holo 的正确抽象不是 finance-only agent，而是：

```text
general agent kernel + finance domain pack
```

---

## 9. 报告/讲稿可直接使用的表述

可以说：

- Holo Kernel v3 已经从概念原型变成可运行、可审计、可演示的 host-owned agent harness。
- 金融任务证明它具备真实工具协作、证据追踪、口径消歧、数值计算和验证能力。
- 其方法论不是把金融题写成规则，而是让 LLM 主导语义判断，host 提供工具、证据、执行、日志、验证和边界。
- Holo 正在从线性 agent loop 升级为 typed graph runtime，以支持并行检索、checkpoint、stream、interrupt、memory 和更强的 UI 可观测性。
- 本地金融题库包含 237 个 checked-in prompts，其中 160 个有答案或 annotation scoring；必须按 FB/FAB、debug/holdout、gold/no-gold 严格分开报告。
- 历史最佳 live 多题证据包括 FinAgent-style full40 strict `95.0%` pass、rescored `97.5%` pass，以及 focused failure regression `11/11`、`12/12`。
- 当前更严格的 LLM-owned 代码线正在补齐 slot binding、verifier-as-tool、toolchain state、cache metrics 和 agent loop telemetry，目标是把能力坐实而不是靠补丁拿分。

不要说：

- Holo 已全面超过金融专家。
- Holo 已解决 FinanceBench/FAB/FinQA 全部任务。
- Holo 已实现完整人脑式并行 agent loop。
- 所有数字都是最新 held-out 结果。
- Holo 展示了模型私有思维链原文。

---

## 10. 下一阶段优先级

### 24 小时内

1. 固化 `finance_working_state` compact packet，让 planner 看到已有 facts、formula traces、verifier 状态和缺口。
2. 保持 processor stable prefix，继续提高 prompt cache hit ratio。
3. 跑小规模 FB debug live，定位当前 slot_bind/source acquisition/synthesis 的主瓶颈。
4. 只在 debug 稳定后跑 FB holdout slice。

### 1 周内

1. 定义 `AgentGraphState` / `AgentGraphDelta` 第一版。
2. dashboard/CLI/report 统一订阅 runtime delta。
3. 单题内部并行 retrieval branch / evidence hypothesis branch。
4. `finance.verify_numeric` 从可用工具变成 planner 常用工具链中的自然一环。
5. 建立 finance failure memory：错误口径、失败来源、成功 source family、repair lesson。

### 1 个月内

1. 将 finance pack 抽象为 domain pack 模板。
2. 建 math pack / physics pack / code pack 的 verifier 工具样板。
3. 完成长任务 checkpoint/resume/replay。
4. 完成大规模 FB/FAB 分集统计和成本/cache 曲线。
5. 将 UI 从 journal projection 升级为真实 graph runtime mirror。

---

## 11. 最终工程判断

Holo Kernel v3 的价值不在“比 ChatGPT 多一个网页界面”。价值在于：

```text
LLM semantic intelligence
  + host-owned tool execution
  + structured evidence and memory
  + verifier-as-tool
  + graph runtime
  + cost/cache telemetry
  + domain packs
```

外部框架给出了方向，但不能替代 Holo 的核心。LangChain 教我们接口生态，LangGraph 教我们状态图和长期运行，Semantic Kernel 教我们 kernel/plugin/filter 分层，Hermes 教我们 schema tool loop，HERMES 教我们 verifier-as-tool。Holo 要把这些原则落成自己的 Kernel v3.1：一个能常驻、能学习、能检索、能计算、能验证、能解释、能被 UI 真实观察的通用高智力工作基座。
