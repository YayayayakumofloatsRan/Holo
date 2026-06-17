# Holo Kernel v3 开源框架参考结论简报

日期：2026-06-16  
分支：`kernel-v3`  
用途：讲稿、报告摘要、下一轮迭代路线确认  

---

## 1. 一句话结论

Holo Kernel v3 不应成为 LangChain、LangGraph、Semantic Kernel 或 Hermes 的包装层。它应该吸收这些框架的工程原则，形成一个 **host-owned、LLM-driven、tool-coupled、memory-aware、graph-observable** 的通用 agent kernel；金融是当前验证场，通用 agent loop 是长期价值。

---

## 2. 我们可以参考什么

### LangChain：参考组件生态

可参考：

- 统一模型接口，避免 provider 细节污染 agent loop。
- 统一工具、检索器、文档、结构化输出和 middleware 抽象。
- 通过 tracing / callback / usage 观测 agent 调用链。

落到 Holo：

- 继续强化 `kernel_v3/processors` 的模型调用协议。
- 把 finance、math、physics、code、workspace 做成 domain/tool pack。
- 每个 pack 提供工具、上下文模板、验证器和 prompt contract，不替模型做答案选择。

不应照搬：

- 不用 LangChain Agent 接管 Holo 主循环。
- 不把文本 callback 当作 typed journal。

### LangGraph：参考状态图 runtime

可参考：

- 显式 StateGraph。
- checkpoint / resume / replay。
- streaming state delta。
- interrupt / human-in-the-loop。
- memory 与 graph state 结合。
- 并行 branch / join。

落到 Holo：

- 把当前 `LoopControllerV3 + journal` 升级为 typed AgentGraph Runtime。
- UI 不再事后拼图，而是订阅真实 graph delta。
- final 后本 turn graph 必须冻结，不再继续跳动。
- 金融检索、候选事实、公式候选、验证器可以并行运行，然后交给 LLM/adjudicator 合并。

不应照搬：

- 不用 graph edge 写关键词规则。
- 不让 host 用边条件决定“哪个数字就是答案”。
- 不为了 demo 画假的 topology graph。

### Semantic Kernel / Microsoft Agent Framework：参考分层治理

可参考：

- Kernel 管 service、provider、memory、telemetry。
- Plugin / Function 管能力暴露。
- Process 管长任务。
- Filter / Middleware 管安全、权限、cache、schema、retry、观测。

落到 Holo：

```text
HoloKernel
  services: model providers, memory, retrieval, journal, telemetry
  plugins: finance, math, physics, code, browser, filesystem
  functions: tool manifests and processor nodes
  processes: long-running task graphs
  filters: policy, schema, provenance, cache, verifier
```

不应照搬：

- 不引入重企业模板拖慢迭代。
- 不把 plugin 变成规则路由系统。

### Hermes Function Calling：参考工具闭环

可参考：

```text
model proposes tool_call
host validates schema and policy
host executes tool
host returns tool_response / tool_error
model observes and continues or finalizes
```

落到 Holo：

- 固化 `ToolManifest -> ToolCall -> ToolResult / ToolError -> Observation`。
- 错误也作为 observation 交回模型。
- host 负责 schema、权限、执行、记录；模型负责下一步判断。
- 简单任务应允许模型判断无需工具，直接结束。

不应照搬：

- 不暴露未授权工具。
- 不让 host 猜测模型意图。

### HERMES Math Agent：参考 verifier-as-tool

可参考：

- verifier 不替模型思考，而是作为模型可调用工具。
- 关键 claim、公式、证明步骤可以被验证器审计。
- 已验证结论进入可复用记忆。

落到 Holo：

- 金融中的 `numeric_verifier`、citation verifier、unit checker、answer cleanliness verifier 应成为工具化 verifier。
- 数学/物理中可接入 CAS、Lean、SymPy、单位维度检查、数值仿真等 verifier。
- host 不决定语义答案，只判断 verifier 输入输出是否结构合规、可审计。

---

## 3. 回看 Holo 开发过程后的主线

Holo 过去几个月并不是在堆功能，主线很清楚：

1. 从聊天脚本走向 host-owned harness。
2. 从单轮回答走向证据耦合的问题解决。
3. 从被动 RAG 走向可管理工作记忆。
4. 从 demo 事件列表走向真实 graph runtime 可视化。
5. 从金融专项能力走向可迁移的通用 agent substrate。

当前最重要的原则仍然是：

```text
LLM owns semantic decisions.
Host owns validation, execution, recording, verification, policy, memory.
```

这也是禁止打表、关键词拦截、阈值规则和 host 代替模型选答案的原因。那些方法会短期抬分，但会破坏泛化能力和论文可信度。

---

## 4. 当前最值得落地的五件事

### P0：AgentGraph Runtime v0

- 定义 `AgentGraphState`、node status、edge event。
- 每个节点只读写 typed state。
- journal、UI、benchmark 消费同一份 graph delta。

### P1：Tool Protocol v1

- 统一 tool manifest、call、result、error、observation。
- 金融工具、检索工具、计算工具、验证工具全部用同一接口。
- 模型提出调用，host 只校验和执行。

### P2：Finance Domain Pack v2

- slot binding 继续由 LLM 做。
- fact ledger / FormulaTrace / numeric verifier / citation verifier 工具化。
- answer synthesizer 只基于 evidence ledger、FormulaTrace 和 citation refs 输出。

### P3：Memory + Cache

- 稳定 prompt prefix，提高 cache 命中。
- 线程工作集 page-in。
- 已验证 claim memory。
- 工具失败记忆。
- 错题反思进入 durable memory，但不进入 holdout 答案泄露。

### P4：Parallel Workbench

- 并行检索：SEC facts、filing text、web、local cache。
- 并行候选：事实候选、公式候选、period 候选。
- 并行验证：numeric、citation、unit、answer cleanliness。
- 合并由 LLM/adjudicator 完成，host 不做语义裁判。

---

## 5. 对报告/论文最有力的表述

可以强调：

- Holo 是一个 host-owned agent harness，而不是普通聊天机器人。
- Holo 的金融能力来自 source-grounded workflow：检索、证据、口径、公式、计算、验证、引用、合成。
- Holo 的通用能力来自同一套 agent loop：观察、判断、调用工具、观察、修复、验证、结束。
- Holo 吸收了 LangGraph 的状态图、Semantic Kernel 的分层、Hermes 的工具闭环和 verifier-as-tool 思路，但保持 LLM 主导语义判断。
- Holo 的 benchmark 体系强调 debug/holdout 分集、live evidence、processor/cache metrics 和可复现实验记录。

应避免：

- 不说“我们已经超过所有金融专家”。
- 不说“规则系统保证正确率”。
- 不把 demo UI 当成真实能力本身。
- 不把人工合理性复核混同为自动 benchmark 分数。

---

## 6. 讲稿版本

Holo Kernel v3 的定位是一个可长期运行的智能工作基座。我们参考 LangChain 的组件生态、LangGraph 的状态图 runtime、Semantic Kernel 的 kernel/plugin/filter 分层，以及 Hermes 的结构化工具调用和 verifier-as-tool 思路，但没有把 Holo 退化成任何一个框架的包装。

它的核心架构是：模型负责语义判断，host 负责工具执行、schema 校验、证据记录、验证、记忆和成本控制。金融任务是目前最强的压力测试，因为它要求系统同时处理检索、报表口径、数值计算、引用和最终答案可信度。这个能力不是金融规则表，而是一套可迁移的 agent loop。未来同一套 loop 可以接入数学证明、物理计算、代码任务和常驻研究任务。

下一阶段最关键的工程路线是三点：第一，把 agent loop 从线性事件升级为 typed graph runtime；第二，把工具接口固化为标准 ToolManifest/ToolCall/ToolResult；第三，把金融能力沉淀成 domain pack，并配套 memory、cache、parallel workbench 和 benchmark observability。这样 Holo 才能既有真实做题能力，又有论文可解释性和长期可迭代性。

---

## 7. 参考材料

本地长文档：

- `docs/KERNEL_V3_OPEN_FRAMEWORK_REVIEW_2026-06-16_ZH.md`
- `docs/KERNEL_V3_FRAMEWORK_REFERENCE_IMPLEMENTATION_DOSSIER_2026-06-16_ZH.md`
- `docs/KERNEL_V3_PROGRESS_2026-06-16_PROCESSOR_USAGE_CACHE_METRICS.md`

本地参考仓库：

- `/tmp/holo_agent_framework_refs/langchain`
- `/tmp/holo_agent_framework_refs/langgraph`
- `/tmp/holo_agent_framework_refs/semantic-kernel`
- `/tmp/holo_agent_framework_refs/hermes-function-calling`
- `/tmp/holo_agent_framework_refs/hermes-math-agent`

官方资料：

- https://docs.langchain.com/oss/python/langchain/overview
- https://docs.langchain.com/oss/python/langgraph/overview
- https://learn.microsoft.com/en-us/semantic-kernel/overview/
- https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/filters
- https://github.com/NousResearch/Hermes-Function-Calling
- https://github.com/aziksh-ospanov/HERMES
- https://api-docs.deepseek.com/guides/kv_cache
