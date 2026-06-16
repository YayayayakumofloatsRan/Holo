# Holo Kernel v3 开源框架参考落成文档

日期：2026-06-16  
分支：`kernel-v3`  
用途：报告讲稿、论文方法章节、Kernel v3.1 迭代路线、工程交接  
状态：可引用落成版。本文聚焦“我们可以参考什么、如何落到 Holo、什么不能做”。

---

## 1. 结论

Holo Kernel v3 不应该成为 LangChain、LangGraph、Semantic Kernel 或 Hermes 的 wrapper。Holo 的核心价值是一个自有的、host-owned 的 agent harness：

```text
LLM semantic intelligence
  + host-owned tool execution
  + durable journal / memory
  + graph-observable agent loop
  + domain packs
  + verifier-as-tool
  + benchmark / telemetry / cache discipline
```

金融是当前最重要的高压场景，因为金融题同时压测检索、证据、表格、口径、期间、单位、公式、引用、验证、成本和最终合成。但金融不能被写成规则脚本。Kernel v3 的正确路线是：

```text
通用 AgentGraph Runtime
  -> 针对任务暴露合适工具和上下文
  -> LLM 负责观察、判断、调用工具、继续判断、最终回答
  -> Host 负责 schema、权限、执行、记录、验证、成本和审计
```

因此我们吸收外部框架的工程原则，而不是交出主 loop。

---

## 2. 已审阅的外部框架

| 框架 | 官方/本地参考 | 可以吸收 | 不应照搬 |
| --- | --- | --- | --- |
| LangChain | <https://docs.langchain.com/oss/python/langchain/overview>；`/tmp/holo_agent_framework_refs/langchain` | 标准 model/tool/retriever/structured-output/middleware 接口；生态 connector；trace/eval 意识 | 不用 LangChain agent 替代 Holo host-owned loop |
| LangGraph | <https://docs.langchain.com/oss/python/langgraph/overview>；`/tmp/holo_agent_framework_refs/langgraph` | state graph、durable execution、persistence、streaming、interrupt、memory、branch/join | 不把 graph edge 写成金融规则；不做假 topology |
| Semantic Kernel / Microsoft Agent Framework | <https://learn.microsoft.com/en-us/semantic-kernel/overview/>；`/tmp/holo_agent_framework_refs/semantic-kernel` | kernel/service/plugin/function/process/filter 分层；插件语义描述；OpenAPI/MCP；企业治理 | 不把 plugin 写成 deterministic answer router |
| Hermes Function Calling | <https://github.com/NousResearch/Hermes-Function-Calling>；`/tmp/holo_agent_framework_refs/hermes-function-calling` | schema tool call、tool response、recursive observation loop、JSON schema repair | 不从自然语言里猜工具参数；不绕过 schema |
| HERMES Math Agent | <https://github.com/aziksh-ospanov/HERMES>；`/tmp/holo_agent_framework_refs/hermes-math-agent` | verifier-as-tool、formal verifier、verified-claim memory | verifier 不替模型选择语义答案 |
| DeepSeek Context Caching | <https://api-docs.deepseek.com/guides/kv_cache> | stable prefix、cache hit/miss telemetry、长上下文复用策略 | 不为了 cache 牺牲任务正确性或把 gold 放进 prompt |

---

## 3. Holo 开发过程文档复核

本次复核了以下内部文档和代码路径：

- `AGENTS.md`
- `README.md`
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
- `kernel_v3/agent/runtime.py`
- `kernel_v3/loop.py`
- `kernel_v3/tools.py`
- `kernel_v3/processors/`
- `kernel_v3/retrieval/`
- `kernel_v3/finance/`
- `kernel_v3/bench/finance.py`
- `kernel_v3/runtime_graph.py`
- `kernel_v3/demo_dashboard.py`

复核结论：Kernel v3 的开发主线是连续的，不是临时刷题脚本。它从早期的对话/记忆/transport 系统，逐步收敛到一个 host-owned agent harness：模型提出语义判断和工具调用，host 执行、记录、验证、恢复和统计。金融基准只是第一个压力最大的 domain pack。

---

## 4. 从外部框架吸收的核心原则

### 4.1 LangChain：接口生态和 harness 边界

LangChain 官方现在直接把 agent 表述为 model + harness；harness 包括 prompt、tools、middleware 和 loop。这个判断和 Holo 的方向一致：LLM 本身不是完整工作系统，必须被一个工程 harness 驾驭。

Holo 应吸收：

- provider-agnostic `ModelClient` / processor interface。
- 标准 `ToolManifest`、`ToolCall`、`ToolResult`。
- retriever / document / loader / splitter / vector store 的边界。
- structured output 和 schema repair。
- middleware 式的观测、预算、权限、cache、trace 层。

Holo 当前对应落点：

- `kernel_v3/processors/` 已经是 provider fabric。
- `kernel_v3/tools.py` 已经有 tool registry 和 schema 边界。
- `kernel_v3/retrieval/` 已经拆出 source discovery、fetch、extract、rank、workbench。
- `kernel_v3/bench/finance.py` 和 `kernel_v3/bench/report.py` 已经开始聚合 processor usage、cache、toolchain、verifier、stage coverage。

下一步：

- 把 tool manifest 固化为跨 domain 协议。
- 把 connector 适配层做薄，避免每个 domain 重写 provider/retrieval glue。
- 保持 Holo 自己的 host-owned loop，不直接用 LangChain agent 接管调度。

### 4.2 LangGraph：状态图、可恢复、可流式观察

LangGraph 最值得吸收的是低层 runtime 思想：long-running、stateful、durable、streaming、human-in-the-loop、memory。Holo dashboard 的同步问题和 graph 跳动问题，本质上都说明当前 runtime graph 还主要是 journal projection，而不是执行时的一等 typed graph。

Holo 应落成：

```text
AgentGraphState
  user_request
  thread_context
  domain_profile
  tool_manifest
  plan_state
  active_branches
  observations
  evidence_ledger
  claim_ledger
  slot_frame
  transform_plan
  formula_traces
  verifier_results
  synthesis_state
  memory_proposals
  cost_cache_metrics
  stop_state
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

必须改进：

- runtime 执行时直接产出 `AgentGraphDelta`，而不是事后猜图。
- UI、CLI、benchmark report 订阅同一 delta stream。
- `finalized` 后当前 turn 图冻结；post-run diagnostics 进入独立区域。
- 支持单题内部 branch/join：并行检索、并行 source family、并行 candidate facts、并行 verifier。

禁止：

- host graph edge 不能以关键词/阈值选择金融答案。
- UI 不能后验拼接虚假 topology。

### 4.3 Semantic Kernel：plugin/function/process/filter 的工程分层

Semantic Kernel 的插件文档强调：plugin 是一组可被 AI 使用的 functions，并且函数的输入、输出、副作用需要有清晰语义描述；同时它明确提醒，AI 应该是决定调用哪些函数的一方。这一点与 Kernel v3 的硬约束完全一致。

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
  plugins / domain packs:
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

对 Holo 的直接价值：

- 将 finance pack 抽象成 domain pack 模板。
- 将 `finance.verify_numeric`、未来 math/physics/code verifier 都注册为 verifier functions。
- 将 schema/policy/provenance/cache/citation 做成 filters，而不是散落在各处。
- 对任务只暴露必要 plugins/tools，降低 token、减少误调用、提高 cache 命中。

### 4.4 Hermes Function Calling：标准工具协议和递归观察闭环

Hermes Function Calling 的价值是朴素但非常正确：

```text
model emits structured tool_call
host validates schema
host executes allowed function
host returns tool_response
model observes result
model continues or answers
```

Holo 应固化：

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

关键设计：

- 错误也是 observation，必须回到模型继续判断。
- 简单 chat 要允许模型直接回答；不能每个 `hi` 都拖入检索 loop。
- 工具模板要告诉模型何时使用、何时不用、参数如何构造。
- host 只执行 schema-valid 的工具调用，不从 prose 中猜意图。

### 4.5 HERMES Math Agent：verifier-as-tool

HERMES Math Agent 把 `verify_one_mathematical_step` 暴露为工具，模型在关键证明步骤上调用 verifier，verifier 返回 correct / incorrect / inconclusive 一类结果。这个思路应成为 Holo 的跨领域能力模板。

金融对应：

```text
LLM identifies claim / metric / formula / numeric answer
-> calls finance.verify_numeric
-> observes supported / unsupported / issue codes
-> repairs, searches more, recalculates, or finalizes
```

未来领域对应：

| Domain | Verifier-as-tool |
| --- | --- |
| finance | `finance.verify_numeric`、citation support、unit/scale check |
| math | Lean、SymPy、Z3、CAS |
| physics | unit/dimension checker、symbolic derivation、numeric simulation |
| code | tests、type checker、static analyzer、sandbox run |
| research | citation/source quality、counter-evidence check |

边界：

- verifier 只验证声明、计算链、证据支持。
- verifier 不替模型选择语义答案。
- verified claims 可以进入 memory proposal，但 durable memory 仍由 host 审批。

### 4.6 DeepSeek Context Caching：成本和速度是系统能力

DeepSeek context cache 的核心规则是 prefix fully match。后续请求如果完整复用已持久化 prefix，就会产生 cache hit；响应 usage 里有 `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens`。

Holo 的 cache 策略：

- stable prefix 前置：系统 contract、tool manifest、domain policy、schema、少变的 source policy。
- dynamic zone 后置：当前 question、最新 observations、当前 facts/gaps。
- 大 evidence 用 refs/support index，不反复塞全量原文。
- processor/task type 维度分别看 cache ratio。
- benchmark report 必须输出 cache hit tokens、miss tokens、hit ratio。

当前已落点：

- `kernel_v3/processors/usage.py` 汇总 provider usage 和 prompt cache。
- `docs/KERNEL_V3_PROGRESS_2026-06-16_PROCESSOR_USAGE_CACHE_METRICS.md` 记录了 processor cache 指标。
- `finance.slot_bind` 和 provider prompt 已开始做 stable prefix 与 compact state。

---

## 5. Holo 当前已具备的基础

| 能力 | 当前落点 | 评价 |
| --- | --- | --- |
| Host-owned agent loop | `kernel_v3/loop.py`, `kernel_v3/agent/runtime.py` | 已形成 observe -> plan -> tool -> observe -> evaluate -> answer 的基本闭环 |
| Processor fabric | `kernel_v3/processors/` | 已支持 task-specific packets、schema、usage/cache metrics |
| Tool registry | `kernel_v3/tools.py` | 已有 schema 和权限边界，需要进一步标准化 manifest/call/result |
| Retrieval workbench | `kernel_v3/retrieval/` | 已覆盖 source discovery、fetch、extract、rank、workbench；仍需并行分支 |
| Finance pack | `kernel_v3/finance/` | 已有 fact ledger、slot binding、formula trace、numeric verifier |
| Runtime graph | `kernel_v3/runtime_graph.py` | 已可 projection；下一步应变成执行时 typed delta |
| Benchmark/telemetry | `kernel_v3/bench/finance.py`, `kernel_v3/bench/report.py` | 已有 pass/cost/cache/toolchain/failure-layer 指标 |
| Demo UI | `kernel_v3/demo_dashboard.py` | 已能演示 chat + runtime console + graph；下一步提高 graph 同步和结构化可读性 |
| Memory | `kernel_v3/memory/`, memory/RAG docs | 已有 durable memory 思路；需要从失败/成功 trace 中形成可用 experience memory |

---

## 6. 为什么这不是“打表”

Kernel v3 必须坚持：

- gold/reference 只能用于 post-run scoring。
- debug split 和 holdout split 分开。
- host 可以抽取候选事实、校验 schema、执行 calculator、记录 provenance。
- LLM 必须负责 metric/period/company/unit/fact binding、是否继续检索、如何合成最终答案。
- verifier-as-tool 是验证，不是答案生成器。

危险部分必须移除或避免：

- 用关键词/阈值决定哪个数字就是答案。
- 用规则判断某一 row 就是模型想要的 metric。
- host 不经 LLM slot binding 自己选事实、套公式、生成答案。
- UI 或 benchmark 为了好看伪造流程。

可接受的 host 能力：

- schema validation。
- permission/cost/budget gate。
- tool execution。
- evidence extraction and provenance recording。
- deterministic arithmetic once the model selected slots/facts/formula.
- post-run scoring and report aggregation。

---

## 7. 对金融能力的直接迭代方向

金融最重要，不应被通用架构讨论稀释。下一阶段金融能力应沿以下路线迭代：

1. **LLM-owned slot binding 更强**
   - 给模型更清晰的 `slot_frame`、candidate facts、formula traces、missing slots。
   - host 不做关键词选择；host 只压缩和展示候选。

2. **Source acquisition 更可靠**
   - SEC companyfacts、filing text、IR PDF、official source directory 并行检索。
   - workbench 让模型判断 source family 和 evidence coverage。

3. **FormulaTrace 成为中心对象**
   - 每个计算答案必须能追到输入 facts、公式、单位、期间和 citation。
   - synthesis 和 verifier 都看同一 compact support index。

4. **finance.verify_numeric 成为自然工具**
   - planner 在最终回答前主动调用。
   - issue codes 返回给模型做 repair hint。

5. **单题内部并行**
   - 并行 search branches。
   - 并行 candidate metric/period hypotheses。
   - 并行 verifier/counter-evidence checks。
   - LLM 负责选择最终分支和结论。

6. **失败记忆**
   - 保存失败来源、错误口径、成功 source family、成功 prompt/tool path。
   - 进入 memory proposal，不自动污染下一题。

7. **严格统计**
   - FB / FAB / FinAgent / workflow challenge 分开报。
   - debug / holdout / public / no-gold 分开报。
   - accuracy、workflow、citation、verifier、cache、latency、failure layer 一起报。

---

## 8. 对通用能力的直接迭代方向

通用能力不应变成金融的副产品。Holo 的 agent loop 应能处理普通问答、研究、代码、文件、数学、物理、role play 和系统常驻任务。

优先落地：

- direct answer path：简单闲聊和无需工具的任务直接回答。
- task profile router：由 LLM/processor 判断任务类型，host 只给可用 profile。
- domain pack template：finance 经验抽象为 `claim/slot/evidence/transform/verifier`。
- memory recall as tool：模型提出 recall，host 返回可用记忆。
- toolchain assembly：模型临时组合 workspace/search/read/compute/write 工具。
- checkpoint/resume：长任务中断后从 state 恢复。
- public trace：展示模型显式计划、工具调用、观察、结构化理由和状态变化，而不依赖私有 hidden chain-of-thought 原文。

跨领域共同骨架：

```text
understand task
-> identify claims / slots / missing evidence
-> choose tools
-> observe results
-> transform / compute
-> verify
-> synthesize
-> remember useful lessons
```

---

## 9. Kernel v3.1 落地路线

### P0：现在就该做

- 固化 compact `toolchain_state` 和 `finance_working_state`，并确保空包不进 provider prompt。
- 让 evaluator 使用 tool/finance observation 后的 refreshed context。
- benchmark/report 增加 context hygiene、cache、processor/task-type 维度。
- 小规模 FB debug live 找当前瓶颈，再跑 holdout slice。
- finance final synthesis 只吃 compact support index，降低乱码和超长上下文失败。

### P1：本周

- 定义 `AgentGraphState` / `AgentGraphDelta`。
- UI/CLI/report 统一订阅 runtime delta。
- 单题内部并行 retrieval/hypothesis branches。
- tool protocol v2：manifest/call/result/schema/cost/authority。
- finance failure memory proposal。

### P2：一个月

- domain pack 模板化：finance -> math/physics/code/research。
- long-task checkpoint/resume/replay。
- verifier-as-tool 泛化。
- 大规模 FB/FAB/FinAgent 分集统计。
- UI 从 journal projection 升级为 runtime mirror。

---

## 10. 讲稿可直接使用的表达

可以说：

- Kernel v3 的核心不是一个金融脚本，而是 host-owned、LLM-driven 的 agent harness。
- 金融是第一个压力测试 domain pack，因为它要求模型在真实来源、口径、单位、公式和引用之间做高强度判断。
- Holo 的方法不是用规则表替代模型，而是把工具、证据、计算器、验证器、记忆和可观测 runtime 暴露给模型，让模型完成专家式工作流。
- 我们审阅了 LangChain、LangGraph、Semantic Kernel、Hermes 等框架，吸收的是接口标准化、状态图、插件治理、schema tool-call、verifier-as-tool 和 cache discipline。
- 下一步 Kernel v3.1 的核心是 AgentGraph Runtime：可恢复、可流式观察、可并行分支、可 checkpoint、可复盘。

不要说：

- Holo 已经全面超过人类金融专家。
- Holo 已解决所有 FinanceBench / FAB / FinAgent 题。
- Holo 的高分来自固定规则或答案表。
- UI 展示的是未加工私有思维链原文。

---

## 11. 最终判断

外部框架的共同结论很清楚：

- LangChain 证明 agent 需要稳定接口和 harness。
- LangGraph 证明复杂 agent 应该是持久、可恢复、可流式观察的状态图。
- Semantic Kernel 证明企业级 agent 需要 plugin/function/process/filter 分层。
- Hermes Function Calling 证明工具调用必须 schema-first。
- HERMES Math Agent 证明 verifier-as-tool 是把 LLM 变可靠的重要方法。
- DeepSeek context caching 证明 prompt layout 和 cache telemetry 是成本能力的一部分。

Holo 的路线也很清楚：

```text
不要替换 Holo loop。
不要写金融规则脚本。
不要伪造 benchmark 或 UI。

要把 LLM 与工具的接口标准化。
要把真实 agent loop 图形化、流式化、可恢复化。
要让 finance pack 成为第一个成熟 domain pack。
要用 benchmark 和 telemetry 证明能力真的变强。
```

这就是 Kernel v3.1 应吸收的框架经验和下一阶段工程路线。
