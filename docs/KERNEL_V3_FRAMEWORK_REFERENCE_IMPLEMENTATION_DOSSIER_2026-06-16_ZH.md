# Holo Kernel v3 开源框架参考与落地实施文档

日期：2026-06-16  
分支：`kernel-v3`  
用途：后续迭代路线、论文/报告材料、讲稿准备、工程交接  

---

## 0. 执行摘要

审阅 LangChain、LangGraph、Semantic Kernel / Microsoft Agent Framework、Hermes Function Calling、HERMES Math Agent，再回看 Holo Kernel v3 过去一路的开发文档后，结论很明确：

Holo 不应该变成任何一个现成框架的薄封装。Holo 的价值在于形成一个 **host-owned、LLM-driven、tool-coupled、memory-aware、graph-observable** 的通用 agent kernel。金融是当前主战场，因为金融题同时压测检索、证据、表格、口径、计算、引用、验证和最终合成；但底层 agent loop 必须保持通用，能够迁移到工程、数学、物理、研究、文件读写、常驻任务和 role play。

外部框架给 Holo 的核心参考不是“照抄 API”，而是五条工程原则：

1. **LangChain**：模型、工具、检索器、文档、回调和集成必须有统一接口。
2. **LangGraph**：复杂 agent 必须是显式状态图，有 checkpoint、stream、interrupt、replay、memory 和可观测执行。
3. **Semantic Kernel / MAF**：企业级 agent 需要 kernel、service、plugin、function、process、filter 的分层。
4. **Hermes Function Calling**：工具调用必须是 schema 化闭环：模型提出调用，host 校验并执行，结果作为 observation 回给模型。
5. **HERMES Math Agent**：强能力不是 host 替模型思考，而是把 verifier 做成工具，让模型在关键声明处主动使用验证器，host 负责严格校验和记录。

Holo 过去的文档已经反复证明一件事：我们走对的主线是 **LLM 做语义判断，host 做边界、执行、验证、审计和记忆管理**。接下来所有优化都应服务于这个主线，禁止重新退化成关键词表、阈值拦截、gold 泄露、host 代替模型选答案。

---

## 1. 本次审阅材料

### 1.1 外部框架

本地参考仓库位于 `/tmp/holo_agent_framework_refs`：

| 框架 | 本地路径 | 本次重点 |
| --- | --- | --- |
| LangChain | `/tmp/holo_agent_framework_refs/langchain` | 组件接口、模型/工具/检索生态、标准集成层 |
| LangGraph | `/tmp/holo_agent_framework_refs/langgraph` | state graph、durable execution、stream、memory、interrupt、tool node |
| Semantic Kernel / MAF | `/tmp/holo_agent_framework_refs/semantic-kernel` | kernel/service/plugin/function/process/filter、多模型和企业级治理 |
| Hermes Function Calling | `/tmp/holo_agent_framework_refs/hermes-function-calling` | tool schema、JSON mode、recursive tool loop、tool response |
| HERMES Math Agent | `/tmp/holo_agent_framework_refs/hermes-math-agent` | verifier-as-tool、Lean 单步验证、已验证声明记忆 |

### 1.2 Holo 内部开发文档

本次重点复核：

- `docs/KERNEL_V3_AGENT_LOOP.md`
- `docs/KERNEL_V3_PROJECT_STATUS_2026-06-14_ZH.md`
- `docs/KERNEL_V3_SYSTEM_REVIEW_2026-06-13_ZH.md`
- `docs/KERNEL_V3_GENERAL_CAPABILITY_LINE1_2026-06-14_ZH.md`
- `docs/KERNEL_V3_FINANCE_ABILITY_METRICS_2026-06-15.md`
- `docs/KERNEL_V3_FB_FAB_EXPERIMENT_SPLITS_2026-06-15.md`
- `docs/KERNEL_V3_PROGRESS_2026-06-15_FINANCE_SLOT_BIND_CACHE.md`
- `docs/KERNEL_V3_PROGRESS_2026-06-16_PROCESSOR_USAGE_CACHE_METRICS.md`
- `docs/KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md`
- `docs/HOLO_ARCHITECTURE_MAP.md`
- `docs/PROCESSOR_ROUTING_AND_COST_POLICY.md`
- `AGENTS.md`

---

## 2. Holo 一路开发过程的真实主线

Holo Kernel v3 的工程演进不是随机堆功能。文档里可以看出四条主线。

### 2.1 从聊天脚本走向 host-owned agent harness

早期 Holo 更像带记忆和 transport 的对话系统。Kernel v3 后，核心变成 host-owned harness：

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

这个方向与 LangGraph、Semantic Kernel、Hermes 的共同结论一致：模型不能直接拥有系统执行权；模型提出计划和工具调用，host 执行、记录、校验和控制停止。

### 2.2 从单轮回答走向证据耦合的问题解决

金融任务暴露了普通聊天模型的弱点：找错报表、拿错期间、混淆 total revenue 和 operating revenue、引用不支持最终数字、公式中间量错误、答案合理但无法审计。

Kernel v3 因此逐步建立：

- retrieval workbench；
- finance fact ledger；
- slot frame；
- transform plan；
- calculator trace；
- numeric verifier；
- citation / source quality；
- synthesis gate；
- benchmark summary 和 failure taxonomy。

这说明 Holo 的“金融能力”不应被定义成背答案，而应定义成 **source-grounded financial reasoning workflow**。

### 2.3 从被动记忆走向可管理工作上下文

`KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md` 已经指出：naive RAG 不是 Holo 的目标。Holo 需要的是 agent memory：

- event memory：journal 是事实序列；
- working memory：当前任务的目标、缺口、成功发现、失败尝试；
- durable memory：经 host 管理的用户/项目/任务记忆；
- research graph：query、source、document、evidence、claim 的关系；
- tool memory：工具失败、来源可靠性、抓取/解析失败经验；
- reflection memory：最终答案或失败后的可复用经验。

这和 LangGraph 的 memory/checkpoint、MemGPT 的虚拟上下文、HERMES 的已验证声明记忆是一条线。

### 2.4 从 demo 事件流走向真实 runtime graph 可视化

近期 dashboard 迭代暴露了一个关键问题：如果 UI 的 topology graph 不是 runtime state 的直接镜像，而是后验拼图，展示就会出现延迟、跳动、已 complete 后还在变动、节点突然一次性点亮等问题。

这说明下一步 UI 不应单独“画得更好看”，而应倒逼 runtime 变成 typed graph state。Graph 可视化应订阅真实 state delta：

```text
node_created
node_started
tool_call_requested
tool_call_running
tool_result_observed
node_completed
edge_activated
branch_joined
finalized
```

UI 只负责渲染，不应发明 agent loop。

---

## 3. 外部框架对 Holo 的具体参考

### 3.1 LangChain：参考接口生态，不接管核心 loop

LangChain 的强项是标准化组件生态。Holo 应吸收：

- `ModelClient` / `Processor` 统一接口；
- `ToolManifest` / `ToolCall` / `ToolResult`；
- retriever、document、loader、splitter、vector store 的抽象；
- callback / telemetry / usage 的标准记录；
- 大量第三方 connector 的接入方式。

落到 Holo：

- `kernel_v3/processors` 应继续成为统一模型调用层；
- `kernel_v3/retrieval` 应更明确地区分 provider、loader、extractor、ranker、evidence reducer；
- finance、math、physics、code、workspace 应作为 domain pack 或 tool pack 注册，而不是散落在 runtime 巨函数里。

不应照搬：

- 不应把 Holo 的主 agent loop 替换成 LangChain Agent；
- 不应让 callback 文本日志替代 typed journal；
- 不应为了生态方便牺牲 host-owned invariant。

### 3.2 LangGraph：下一阶段最重要的架构参考

LangGraph 的核心价值是显式状态图、长任务可恢复和流式状态更新。Holo 当前已经有 journal 和 taskgraph 胚胎，但执行仍偏线性 loop。下一步应该把 runtime 对象升级为 typed state graph。

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

关键要求：

- 每个节点有 typed input/output；
- 每个状态迁移写 journal；
- UI 只订阅 graph delta；
- checkpoint 能恢复长任务；
- interrupt 能处理权限、证据不足、成本上限、用户确认；
- branch/join 能支持并行检索、并行候选公式、并行反证。

禁止事项：

- 不用 graph edge 写金融关键词规则；
- 不让 host 用 graph 边决定最终数字；
- 不为了展示画假图。

### 3.3 Semantic Kernel / Microsoft Agent Framework：参考分层治理

Semantic Kernel / MAF 值得参考的是企业级分层：

```text
Kernel: 服务容器和运行边界
Service: model provider、memory、journal、retrieval、telemetry
Plugin: finance、math、physics、code、workspace、browser
Function: 可调用工具或 processor node
Process: 长任务流程、恢复、branch/join
Filter: schema、安全、成本、cache、citation、numeric verifier
```

Holo 映射：

| SK/MAF 概念 | Holo 应落点 |
| --- | --- |
| Kernel | `HoloKernel` / runtime service container |
| Plugin | domain pack / tool pack |
| Function | `ToolManifest` + processor node |
| Process | AgentGraph / MissionRuntime |
| Filter | policy gate、schema validator、usage/cost、citation/numeric gates |
| Memory | durable memory + working set + research graph |
| Telemetry | journal + processor usage + benchmark report |

不应照搬：

- 不引入过重样板；
- 不把 plugin 变成规则系统；
- 不让多 agent 概念掩盖当前最重要的单 agent loop 质量。

### 3.4 Hermes Function Calling：把工具协议彻底标准化

Hermes Function Calling 证明：工具调用闭环必须显式。Holo 应把所有工具统一成：

```text
ToolManifest {
  name,
  description,
  args_schema,
  result_schema,
  side_effects,
  cost_class,
  cache_policy,
  provenance_policy,
  safety_policy
}

ToolCall {
  call_id,
  tool_name,
  arguments,
  requested_by_processor,
  requested_at_node,
  model_message_id
}

ToolResult {
  call_id,
  status,
  observation,
  citations,
  artifacts,
  usage,
  cache_hit,
  error
}
```

关键设计：

- 模型决定是否调用工具、调用哪个工具、传什么参数；
- host 校验 schema、权限、预算、side effect；
- 错误也作为 observation 回给模型；
- 简单任务允许模型直接回答，不强迫重型 loop；
- 复杂任务允许递归 tool loop，但必须有预算、停止和可恢复状态。

### 3.5 HERMES Math Agent：verifier-as-tool 的通用价值

HERMES Math Agent 最值得 Holo 借鉴的不是 Lean 细节，而是模式：

```text
模型提出一个非平凡声明
-> 调用 verifier 工具
-> verifier 返回 correct / incorrect / inconclusive
-> 模型修正或继续
-> host 记录已验证声明
```

金融可以对应：

| 数学 HERMES | 金融 Holo |
| --- | --- |
| proof step | financial claim / formula step |
| Lean verifier | calculator / numeric verifier / citation verifier |
| autoformalization | slot binding / formula binding |
| verified theorem memory | verified finance fact / formula trace memory |
| inconclusive | evidence insufficient / citation unsupported |

这也能迁移到数学、物理和代码：

- 数学：调用 CAS、Lean、Sympy、数值检查；
- 物理：单位分析、维度检查、仿真/计算工具；
- 代码：测试、lint、type check、static analysis；
- 研究：citation verifier、source authority verifier。

重要边界：verifier 不是替模型思考，而是提供可审计反馈。模型仍负责选择下一步和解释结果。

---

## 4. Holo 应立即吸收的设计

### 4.1 Typed AgentGraph Runtime

当前 agent loop 已经能工作，但仍有大量后验 journal 拼接。应把真实执行改造成 typed graph runtime：

- graph state 是唯一真相；
- journal 是 graph state delta 的持久记录；
- dashboard 是 graph state 的实时投影；
- benchmark trace 从 graph state 直接汇总；
- resume/replay 从 checkpoint 恢复。

短期可先做 v0，不需要完全重写：

1. 在现有 loop 外包一层 `AgentGraphTrace`；
2. 每个 processor/tool/gate 写 `node_event` 和 `edge_event`；
3. UI 改为订阅这些事件；
4. 最后再把 loop 控制权逐步迁移到 graph runtime。

### 4.2 Domain Pack 协议

金融不应是特殊脚本，而应是第一个成熟 domain pack：

```text
DomainPack {
  name,
  prompt_contract,
  tool_manifests,
  context_compiler,
  verifier_tools,
  synthesis_profile,
  benchmark_profile,
  memory_policy
}
```

Finance Pack 包含：

- SEC / EDGAR / company facts / filings 工具；
- financial fact ledger；
- metric and period slot binding prompt；
- calculator；
- numeric verifier；
- citation verifier；
- answer cleanliness verifier；
- FB/FAB benchmark profiles。

Math Pack 可包含：

- calculator；
- Sympy；
- Lean/HERMES-like verifier；
- proof-step claim ledger；
- theorem/lemma memory。

通用 Pack 可包含：

- direct chat；
- workspace read/write；
- retrieval；
- memory recall；
- system/time；
- roleplay/writing。

### 4.3 Model-owned semantic binding

必须保持的红线：

- host 不用关键词表决定 period/metric/company；
- host 不用阈值决定哪个数字是答案；
- host 不读取 gold 进入 runtime；
- host 不替模型把候选 fact 绑定到 final answer。

host 可以做：

- schema validation；
- fact id existence validation；
- numeric parseability；
- formula dependency execution；
- provenance/citation support check；
- cache/usage/error observability；
- post-run scoring。

这条线是 Holo 区别于“刷题脚本”的核心。

### 4.4 Parallel Workbench

用户提出的并行化方向应采纳。成熟形态不是“并行跑更多题”这么简单，而是单题内部并行：

```text
Planner proposes branches:
  evidence_branch: source acquisition and filing lookup
  metric_branch: candidate facts and period reasoning
  formula_branch: required formulas and calculator plan
  critique_branch: counterevidence / ambiguity / unsupported numbers

Host runs allowed branches concurrently.
ObservationReducer merges results.
LLM judges conflicts and chooses next action.
Verifier checks final answer.
```

收益：

- 降低长题 wall time；
- 减少单一路径搜索失败；
- 更像人类 analyst 同时查文档、列公式、检查口径；
- 更适合 UI 展示真实拓扑。

风险：

- token 成本可能上升；
- 分支质量差会制造噪声；
- 必须有 branch usefulness 统计。

因此并行化必须和 cache、context compaction、branch budget 一起做。

### 4.5 Memory Page-In 与错误学习

Holo 的记忆系统已经有结构，但金融能力提升需要更主动的 memory：

- 记住某题失败在哪一层：source acquisition、slot binding、formula、synthesis、citation；
- 记住某来源族对某类问题有效；
- 记住模型常混淆的财务口径，但以“可复用提示/反思”形式进入，不是 host 规则；
- 记住 verified formula trace 和 citation pattern；
- 每次进入 planner 前 page-in 少量高价值经验。

注意：错误学习不是把题目答案写入记忆。题库 gold 和最终答案不能污染 runtime。

### 4.6 Cache-Friendly Prompt Contract

DeepSeek cache 命中率已经被证明对成本和速度非常关键。Holo 应继续采用稳定前缀：

```text
stable kernel invariant
stable processor schema
stable tool manifest
stable domain prompt contract
stable answer profile
durable memory digest
thread working set
task-local evidence/facts
dynamic user request / latest observation / errors
```

需要记录：

- per-processor cache hit/miss tokens；
- task.compile / slot_bind / numeric_judge / synthesizer 的 cache ratio；
- prompt section hash；
- cache ratio 和准确率/耗时的关系。

缓存优化不能改变语义归属。它只是 prompt 编排和成本工程，不是规则决策。

### 4.7 Evaluation as First-Class Runtime

从内部文档看，过去最大风险之一是 debug、holdout、fake、live、manual reasonable judge 混在一起。后续必须固定口径：

- FB debug：offset `0-9`，只用于系统调试；
- FB holdout：offset `10-149`，用于真正评估；
- FAB dev10：小型 scored development；
- FAB public27：无 public gold，做行为/工作流/人工复核；
- Holo workflow challenge：压力和覆盖，不当作官方准确率。

每次 run 必须记录：

- item_count；
- pass_rate；
- numeric_accuracy；
- workflow/substrate score；
- calculator/formula trace rate；
- citation rate；
- processor task type counts；
- cache hit ratio；
- error counts；
- failure taxonomy；
- 是否 live；
- 是否 debug split；
- 是否 holdout。

---

## 5. 当前能力与差距的诚实判断

### 5.1 已经能证明的能力

从现有文档和 live 结果看，Holo 已经能展示：

- host-owned agent loop；
- live model processor fabric；
- tool execution and journal；
- retrieval workbench；
- finance fact ledger；
- calculator trace；
- numeric/citation/synthesis gates；
- Windows demo dashboard；
- general gauntlet；
- DeepSeek cache usage metrics；
- FB/FAB split policy；
- FinAgent-style multi-item live score历史最好 full40 `95.0%`，rescored `97.5%`；
- FinanceBench doc retrieval live10 目前中等，暴露真实 source acquisition / binding / synthesis 难点。

### 5.2 当前短板

目前不应夸大为“通吃金融”。短板主要是：

- 单题内部 graph 还不够显式；
- UI 有时仍像后验事件展示，不是真 graph runtime；
- finance slot binding 在噪声 fact 下仍不稳定；
- synthesis context 过大，容易走 compact rescue；
- numeric verifier 和 final answer clean-up 仍需更强；
- 内部并行只做到题目级，单题分支并行尚未成熟；
- memory 仍偏被动，未形成强错误学习闭环；
- cache 指标刚开始统一，还没用于大规模优化决策；
- FinanceBench doc retrieval 的真实源获取和口径绑定仍是主要难点。

### 5.3 关键判断

Holo 现在最强的真实能力不是“像 ChatGPT 一样聊天”，而是：

> 在 host 管理的工具、证据、计算、验证和记忆边界内，让 LLM 完成可审计的复杂问题求解。

因此展示和论文应强调：

- agent loop substrate；
- finance as stress test；
- evidence-coupled reasoning；
- verifier-as-tool；
- graph-observable execution；
- cost/cache-aware persistent agent；
- domain pack generalization。

---

## 6. 论文/报告可使用的表述

### 6.1 一句话版本

Holo Kernel v3 is a host-owned, LLM-driven agent harness that couples model reasoning with tools, evidence ledgers, verifier feedback, durable memory, and graph-level observability, with finance as the first high-pressure domain pack.

中文：

Holo Kernel v3 是一个宿主拥有执行权、LLM 拥有语义判断权的 agent harness；它把模型推理与工具、证据账本、验证器、长期记忆和图级可观测性耦合起来，并以金融作为第一个高压领域包。

### 6.2 可以强调的创新点

- **Host-owned / model-driven boundary**：模型提出计划和判断，host 执行和验证。
- **Evidence-coupled agent loop**：答案必须经过证据、引用、计算和 verifier 支撑。
- **Domain pack architecture**：金融是第一个 pack，不是写死脚本。
- **Verifier-as-tool**：验证器反馈进入 loop，而不是只做离线评分。
- **Graph-observable runtime**：agent loop 可被 UI 和 benchmark 观察。
- **Cache-aware processor fabric**：按 processor 统计 token、cache、错误和耗时。
- **Memory as managed context**：长期记忆不是聊天记录堆积，而是可 page-in 的工作上下文。

### 6.3 应避免的表述

- 不说“完全超过专家”。
- 不把 debug split 当 holdout。
- 不把 fake/offline 控制实验当 live 能力。
- 不说 host 自动知道答案。
- 不说暴露原始隐式思维链是能力来源；产品展示应依赖 public structured trace、tool calls、observations、verifier feedback 和 model-provided summaries。

---

## 7. 下一阶段工程路线

### P0：稳定金融做题能力

目标：让 FB/FAB 上的真实 live 成绩可持续提高。

任务：

- 修 finance slot binding prompt，使模型更稳地从 raw facts 判断 period/metric；
- 强化 compact synthesis packet，避免 500k+ prompt 触发 rescue；
- 把 calculator traces、selected facts、citations 作为 final synthesis 主上下文；
- 强化 unsupported number repair；
- 每次 run 输出 processor cache/error/task type breakdown；
- 严格按照 FB debug / holdout / FAB dev/public 分集报告。

验收：

- FB debug offset 0-9 单题/小批稳定；
- FB holdout offset 10+ 开始跑；
- FAB dev10 保持 numeric/tool trace；
- summary 可解释失败层。

### P1：AgentGraph v0

目标：把当前线性 loop 变成可观察 typed graph。

任务：

- 定义 `AgentGraphState` 和 `AgentGraphEvent`；
- processor/tool/gate 写 node event；
- UI graph 只订阅真实 event；
- complete 后不再发生同一 turn 的新增执行事件；
- branch/join 支持并行 workbench v0。

验收：

- dashboard graph 不跳画幅；
- answer complete 与 runtime stopped 同步；
- node 状态和真实 tool/model 调用一致；
- 可以从 graph 直接还原 benchmark trace。

### P2：Tool Protocol v1

目标：统一工具接口，减少 runtime 特例。

任务：

- 标准化 `ToolManifest`、`ToolCall`、`ToolResult`、`ToolError`；
- 所有工具返回 observation + artifacts + citations + usage；
- schema 错误和执行错误作为 observation 回给模型；
- tool registry 支持 domain pack 注册。

验收：

- finance/retrieval/memory/system/calculator 使用统一协议；
- planner packet 中工具说明稳定排序；
- policy gate 不依赖工具名硬编码语义。

### P3：Memory Page-In v1

目标：让记忆服务能力，而不是污染上下文。

任务：

- thread working set 标准化；
- failure memory 进入 planner；
- tool/source family outcome 统计；
- verified finance trace 以非答案形式保存为经验；
- memory proposal 审批和去重。

验收：

- 重复错误减少；
- planner 能看到过去失败层；
- prompt token 不因记忆无限增长。

### P4：Parallel Workbench v0

目标：单题内部并行，而不是只并行跑题。

任务：

- planner 可提出多个 branch；
- host 并行执行 retrieval/calculation/critique；
- observation reducer 合并；
- LLM 选择继续、修复或合成；
- 统计 branch usefulness。

验收：

- 同类难题 wall time 降低；
- source acquisition failure 减少；
- 无效分支比例可观察。

### P5：Demo UI 真实化

目标：让展示界面看起来专业，并且反映真实 runtime。

任务：

- 右侧 chat 保持主交互；
- 左侧 graph 展示真实节点/边/状态；
- console 显示结构化模型输出、tool call、observation、verifier；
- event 信息集中到显眼位置；
- 支持 thread、clear、case selector、stable hard demos；
- 不显示虚假的 hidden context，不把后验事件伪装成实时执行。

验收：

- 用户能从 UI 看懂 agent loop；
- 简单问题不会陷入重型 loop；
- 金融 demo 能展示 evidence -> calculation -> verifier -> final。

---

## 8. 立即可执行的任务清单

短期最值得做的不是继续盲目加复杂度，而是以下闭环：

1. **把 processor/cache breakdown 接入 CLI 和 benchmark report**  
   让每次 live run 立刻显示 task.compile、slot_bind、numeric_judge、synthesis 的成本和失败。

2. **跑 FB debug 小批 live**  
   使用 offset 0-9，不进入 holdout；目标是定位当前 pipeline 瓶颈。

3. **修 finance slot binding 和 synthesis compact packet**  
   这是当前金融准确率最关键的工程点。

4. **定义 AgentGraphEvent v0**  
   先不重写 runtime，只让现有 loop 发真实 graph event，解决 UI 同步和 topology 失真。

5. **建立 branch-aware retrieval workbench 草案**  
   先允许模型提出 evidence / formula / critique 三类并行分支，再逐步执行。

6. **把错误学习写入 memory proposal**  
   只写失败类型、来源策略、验证经验，不写题目答案和 gold。

7. **更新报告口径**  
   分开写历史最好 live 成绩、当前 active branch 状态、FB/FAB split、下一步 eval 计划。

---

## 9. 最终判断

Holo Kernel v3 已经不是一个普通聊天 UI，也不是简单金融刷题脚本。它已经有了一个高智力工作基座的关键骨架：LLM 语义判断、host 工具执行、证据账本、计算验证、journal、memory、benchmark 和可视化。

但要让它真正成为强金融 agent，还必须把三件事坐实：

1. **把真实 agent loop 图形化和状态化**，不是后验事件拼图；
2. **把金融问题解决压成稳定 domain pack**，不是散落的特例和 prompt 修补；
3. **把 benchmark/cost/cache/failure 统计变成每次迭代的仪表盘**，不是跑完后凭感觉判断。

外部框架给出的方向与 Holo 当前最正确的路线一致：不要让 host 替模型思考，也不要让模型直接乱执行。Holo 应该做的是把 LLM 放进一个强工具、强证据、强验证、强记忆、强可观测的工作环境里，让它真正能解决复杂问题。

