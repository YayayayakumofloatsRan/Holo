# Holo Kernel v3 项目状态总览

日期：2026-06-14  
分支：`kernel-v3`  
用途：结项汇报、论文/报告材料、demo 讲稿准备、后续工程交接

## 摘要

Holo Kernel v3 当前已经从早期阶段化实验推进为一个可运行、可审计、可演示的 host-owned agent harness。它的核心定位不是“金融题脚本”，而是一个通用高智力工作基座：LLM 负责语义判断、任务分解、搜索策略、证据选择和答案合成；host 负责工具接口、权限、执行、日志、证据、数值验证、状态管理和可视化。

金融是当前最重要的压力测试场景。原因很简单：金融题同时要求检索、文档定位、表格理解、口径消歧、公式计算、证据引用和错误前提识别。一个能在金融任务中稳定工作的 harness，才有资格继续迁移到数学、物理、代码研究和行业分析任务。

当前可汇报的核心成果：

- Kernel v3 已形成完整 agent loop：semantic intake、task compile、planner、tool execution、retrieval workbench、claim/slot/transform/verifier/synthesis gates、journal。
- Windows demo UI 已可录制，能展示 chat、runtime console、agent loop topology、tool/retrieval/verifier/final answer 等运行过程。
- 金融子系统已有真实 live benchmark 证据：历史失败集达到 `12/12`，FinAgent full40 live 原始严格分达到 `38/40 = 95.0%`，旧结果重评分达到 `39/40 = 97.5%`。
- 关键口径失败 FE_020 已 live 单题修复：Chevron FY2024 revenue 正确回答 `$193.414B Sales and other operating revenues`，不再误选 `$202.792B Total Revenues and Other Income`。
- 系统仍存在明显短板：单题平均 token 和耗时偏高，agent loop 内部搜索分支尚未真正并行化，部分题答案正确但 verifier/synthesis gate 不够干净。

## 当前系统定位

Kernel v3 的一句话定义：

> Holo Kernel v3 是一个 host-owned agent harness：模型提出语义判断和行动，host 验证、执行、记录、组织证据并检查答案，使模型的智能可以稳定地接入工具、记忆、检索和领域工作流。

关键不变量：

- LLM 是核心语义决策者。
- host 不直接替代模型作最终金融判断。
- host 负责工具暴露、权限校验、证据验证、数值验证、日志和停止边界。
- benchmark gold/reference 只用于 post-run scoring，不能进入 planner、retrieval、synthesis、memory。
- 不使用答案表欺骗测试。
- 不用关键词拦截替代 agent 判断；确定性逻辑主要用于证据抽取、候选排序、边界验证和评分。

## 架构现状

### 1. Chat 与线程状态

主要代码：

- `kernel_v3/chat/`
- `kernel_v3/journal.py`
- `.state/kernel_v3/threads/`

能力：

- 多线程 chat。
- per-thread transcript。
- journal-derived summary。
- demo dashboard 订阅事件流。
- 用户可以从 Windows 浏览器输入问题，WSL 侧 Holo 执行 agent loop。

当前价值：

这让 Holo 不只是 CLI 工具，而是一个可交互、可观察的工作系统。演示时可以看到用户输入、模型路由、工具调用、检索、证据、verifier、final answer 之间的关系。

### 2. Processor Fabric

主要代码：

- `kernel_v3/processors/`

能力：

- schema-first model call。
- task-specific processor：semantic intake、planner、evaluator、task.compile、retrieval.workbench、finance.numeric_judge、synthesizer。
- JSON repair。
- provider usage/journal。
- fake provider 与 live DeepSeek provider。

当前价值：

Kernel v3 不是把整题直接扔给模型，而是把复杂任务拆成结构化 processor packet。每个 packet 有 schema、上下文和日志，便于调试和复现。

### 3. Agent Loop

主要代码：

- `kernel_v3/agent/runtime.py`
- `kernel_v3/loop.py`
- `kernel_v3/agent/workloop.py`

典型流程：

1. 用户输入进入 chat runtime。
2. route/semantic intake 判断任务类型。
3. task compiler 生成 `TaskSpec / EvidenceSpec / TransformSpec`。
4. planner 提出下一步动作。
5. host 通过 policy gate 和 tool registry 执行动作。
6. retrieval/workbench/verifier 形成证据和诊断。
7. synthesizer 生成答案。
8. finance numeric judge / synthesis gate 检查核心数值、引用和支持度。
9. journal 记录全过程。

当前价值：

这已经是一个可审计 agent loop，而不是一次性问答。它能解释“为什么继续检索、为什么结束、答案根据什么、哪里失败”。

### 4. Retrieval Workbench

主要代码：

- `kernel_v3/retrieval/`
- `kernel_v3/retrieval/operator.py`
- `kernel_v3/retrieval/extract.py`

能力：

- 查询规划。
- SEC/companyfacts/EDGAR/live HTTP/source directory。
- 文档抓取、抽取、引用。
- source quality。
- rejected evidence。
- LLM workbench 判断 evidence 是否足够、缺什么、下一步查什么。

当前价值：

这是 Holo 从“搜索一下”变成“研究式取证”的关键。金融、政策、技术研究都需要这个循环。

### 5. Finance Domain Pack

主要代码：

- `kernel_v3/finance/`
- `kernel_v3/finance/fact_ledger.py`
- `kernel_v3/finance/formula_planner.py`
- `kernel_v3/bench/finance.py`

能力：

- FinanceFact ledger。
- SEC concept / label / period / source ranking。
- revenue / net income / capex / PP&E / COGS / DIO 等公式输入抽取。
- calculator trace。
- numeric verifier。
- synthesis gate。
- benchmark import/scoring。

当前价值：

金融能力不是单个答案，而是一条链：

> 找对来源 -> 找对口径 -> 找对期间 -> 找对单位 -> 必要时计算 -> 引用 -> 验证 -> 合成。

这条链已经可以在 live benchmark 中工作。

### 6. Generic Substrate

主要代码：

- `kernel_v3/substrate/`

核心对象：

- `ClaimLedger`
- `SlotFrame`
- `EvidencePolicy`
- `TransformPlan`
- `VerifierGateResult`

当前价值：

这些对象让金融经验可迁移到其他领域。数学证明、物理推导、代码修复、研究报告，本质上都需要 claim、slot、evidence、transform、verification。

## 金融 benchmark 现状

### 已验证 live 结果

| 结果 | 文件 | 结论 |
| --- | --- | --- |
| 历史 full40 失败集回归 | `.state/kernel_v3/bench/finance/run_full40_previous_failures_after_nonitemized_headline_live.summary.json` | `12/12 passed`, pass rate `1.0` |
| full11 失败回归 | `.state/kernel_v3/bench/finance/run_failure_regression_full11_after_annual_margin_rank_live.summary.json` | `11/11 passed`, numeric/adversarial accuracy `1.0` |
| FinAgent full40 live | `.state/kernel_v3/bench/finance/run_finagent_full40_after_nonitemized_headline_live_20260614.summary.json` | `38/40 passed`, pass rate `0.95`, numeric accuracy `0.9487` |
| full40 旧结果重评 | `.state/kernel_v3/bench/finance/run_finagent_full40_after_nonitemized_headline_live_20260614.rescored.summary.json` | `39/40 passed`, pass rate `0.975`, adversarial accuracy `1.0` |
| FE_020 post-fix live | `.state/kernel_v3/bench/finance/run_fe020_after_operating_revenue_priority_live_20260614.summary.json` | `1/1 passed`, Chevron revenue 口径修复 |

### 关键能力进展

1. **年度口径优先**
   - FY/annual/full-year 问题优先年度 10-K/companyfacts。
   - 修复 Apple net profit margin 中季度值和 tax 值污染。

2. **收入指标消歧**
   - 区分 `Sales and other operating revenues`、`Total revenues and other income`、`RevenueFromContractWithCustomerExcludingAssessedTax`、`Revenues`、`net revenues`、`operating revenues`。
   - FE_020 修复证明该能力有效：plain total revenues 问题不再抢 broader other-income subtotal。

3. **未单独披露 / 不可得判断**
   - 对 `not separately itemized` 类问题，合成器必须先说不可单独披露，再给 proxy/context。
   - FE_032 在 full12 回归和 full40 中都通过。

4. **source-grounded actual correction**
   - 对 gold 中错误前提或 excerpt 不完整的题，允许模型给出更完整的真实答案。
   - FE_034 live 找到 NVIDIA Data Center FY2024 segment revenue `$47.5B`，说明模型能超越 excerpt-limited gold；严格 scorer 仍需 clean rescore 完成闭环。

5. **compact repair**
   - synthesis 或 numeric support 出问题时，runtime 构建 compact finance repair packet，包含 ranked finance facts、formula traces、citations 和少量证据，而不是把全量噪声重新塞给模型。

## 用户建议采纳情况

### 已采纳

- **LLM 做核心判断**：prompt 和 runtime 明确写入 `semantic_decision_owner=model`，host 是 candidate map、provenance validator 和 executor。
- **工具标准化**：planner 使用标准工具接口，如 `retrieval.run`、`calculator.compute`、`respond`。
- **金融提示词精调**：合成器、numeric judge、finance fact ledger 都增加了金融口径、来源、单位、引用、不可得判断的 contract。
- **并行跑题**：benchmark harness 支持 `--parallel`，每题独立 worker/state/journal；实际 full40 使用 parallel live run。
- **上下文压缩**：compact synthesis repair packet 将 repair evidence/citation 限制到小集合。
- **更多 live 测试**：已跑 full40、失败回归、单题修复验证，优先 live 而不是 fake offline。

### 部分采纳

- **agent loop 内部并行化**：目前只做到题目级并行；单题内部还没有真正的搜索分支并行、假设分支并行、结果竞争与模型汇总。
- **长期记忆优化**：结构已有，但这轮主要精力在 benchmark 和 finance substrate，未完成“从错误中自动学习”的强闭环。
- **低成本高效率**：做了 compact repair，但 full40 平均仍约 `242k tokens/题`、`168s/题`，成本仍高。

### 未完成

- 单题内部并行搜索。
- 几百/几千题规模统计。
- full40 post-fix clean rerun。
- 将当前文档和代码整理后 push 到远端。

## 当前 Demo 状态

Demo 已录制。当前 dashboard 主要价值：

- 展示 Holo 不是单次 chat，而是带工具、证据、verifier、final answer 的可观察 runtime。
- 展示 agent loop topology、runtime console、tool/retrieval/synthesis 流。
- 展示 finance benchmark case 及对应 trace。

建议演示讲法：

> 这个 demo 的重点不是 UI 本身，而是让观众看到：一个复杂金融问题如何进入 agent loop，模型如何提出下一步，host 如何调用工具并记录，检索如何形成证据，计算如何被验证，最终答案如何带 citation 输出。

## 当前弱点

1. **成本高**
   - full40 平均 `242k tokens/题`。
   - 有些题 7-8 次 retrieval，说明 loop 收敛还不够快。

2. **verifier/synthesis gate 不稳定**
   - full40 verifier gate pass rate `0.8`。
   - 有些题 benchmark 对了，但 evidence support gate 不够干净。

3. **内部并行不足**
   - 题目级并行已可用。
   - 单题内部没有并行假设/并行搜索/并行工具分支。

4. **FinanceBench / FinQA 更广泛任务仍未闭合**
   - 当前强项是 source-grounded fact extraction、metric disambiguation、可审计计算。
   - DCF/LBO、复杂 PDF 表格、长期多文档 research 仍需要更多工作。

5. **文档与代码尚未统一提交**
   - 当前 worktree 有大量修改。
   - 需要整理 commit 和 push 到 `kernel-v3`。

## 汇报建议口径

不要说：

- Holo 已经全面超过金融专家。
- Holo 已解决 FinanceBench/FAB/FinQA 全部任务。
- Holo 已经实现完整人脑式并行 agent loop。

可以说：

- Holo Kernel v3 已经从概念原型变成可运行、可审计、可演示的 agent harness。
- 金融任务证明它具备真实工具协作、证据追踪、口径消歧和数值验证能力。
- live benchmark 中已经出现可汇报的高分：历史失败集 `12/12`，full40 严格 `95%`，重评 `97.5%`。
- 这不是打表；gold 不进入 prompt，答案来自 live retrieval、finance fact ledger、calculator/verifier/synthesis。
- 下一阶段重点是单题内部并行搜索、上下文压缩、长期记忆和大规模公开题库统计。

## 下一步工程路线

### 24 小时内

1. 完成 full40 post-fix clean rerun 或至少完成 source-grounded rescore。
2. 整理当前修改，补齐 README 和 benchmark 文档。
3. 将文档和代码 push 到 `kernel-v3`。
4. 把 demo 讲稿和结果表固化成结项材料。

### 1 周内

1. 实现单题内部并行搜索分支：
   - LLM 提出多个 evidence hypotheses。
   - host 并行执行 retrieval branches。
   - LLM workbench 汇总和选择。
2. 将 compact repair 扩展为通用 context compression。
3. 强化 durable memory：保存失败模式、成功策略、领域口径。
4. 跑更大公开题库切片，形成统计可信度。

### 论文/报告方向

建议核心论点：

> Kernel v3 demonstrates that a host-owned agent harness can turn a general LLM into an auditable financial research worker by combining model-owned semantic judgment with host-owned evidence, tool execution, state, and verification.

可写优化路线：

- Agent-loop parallelization。
- Context compression。
- Toolchain reinforcement。
- Evidence-grounded finance reasoning。
- Model-owned semantic judgment with host verification。

