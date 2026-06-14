# Holo Kernel v3 Demo 讲稿提纲

日期：2026-06-14  
用途：录制 demo 后的结项汇报讲稿、答辩提纲、论文口头介绍

## 1. 开场：我们做的不是一个聊天机器人

建议讲法：

> Holo Kernel v3 的目标不是再做一个 ChatGPT 式聊天界面。它是一个 host-owned agent harness：模型负责思考和判断，系统负责工具、证据、执行、日志、验证和长期状态。我们希望把通用大模型组织成一个能长期工作的数字研究员。

要点：

- 不是单轮问答。
- 不是固定规则脚本。
- 不是金融答案表。
- 是 LLM + tools + host verification + memory/state 的工作基座。

## 2. 为什么选择金融作为压力测试

建议讲法：

> 金融题很适合测试一个 agent 是否真实有用，因为它不只问模型知道什么。它要求模型找到正确文件、理解表格、区分口径、做计算、给引用，还要知道什么时候不能回答。

展开：

- `revenue` 在不同公司和报表里可能不是同一个概念。
- `total revenues` 可能和 `total revenues and other income` 不同。
- fiscal year、quarter、TTM 容易混淆。
- Data Center revenue、segment revenue、total revenue 不能互相替代。
- 金融结果必须 source-grounded。

结论：

> 如果 Holo 能在金融任务里稳定工作，它就不是一个只会聊天的系统，而是一个能被工具和证据约束的工作型 agent。

## 3. Kernel v3 的核心架构

可以配合图讲：

```text
User
  -> Chat Runtime
  -> Semantic Intake
  -> Task Compile
  -> Planner
  -> Policy Gate
  -> Tools: retrieval.run / calculator.compute / memory.recall
  -> Evidence + ClaimLedger + SlotFrame + TransformPlan
  -> Verifier / Numeric Judge / Synthesis Gate
  -> Final Answer + Citations + Journal
```

讲法：

> 模型不是直接控制系统。模型提出动作，host 验证动作是否合法，然后执行工具。工具结果再进入模型判断。整个过程写入 journal，demo UI 展示的就是这条链路。

强调：

- LLM owns semantic judgment。
- Host owns validation and execution。
- Journal makes the loop auditable。
- Tools are standardized interfaces。

## 4. Demo 中观众应该看什么

演示重点不是“界面好看”，而是结构：

1. 用户在 chat 中输入金融问题。
2. Holo 进入 agent loop，而不是直接回答。
3. Runtime console 显示模型 packet、工具调用、检索、证据、verifier、final answer。
4. Topology graph 显示当前阶段。
5. 最终答案带 source/citation/metric reasoning。

建议讲法：

> 这个界面展示了 Holo 和普通聊天机器人的差别：普通聊天模型只给一个答案；Holo 展示从问题到证据、从证据到计算、从计算到验证、从验证到答案的工作流。

## 5. 金融能力展示口径

当前最稳的展示能力：

- 财报事实抽取。
- 指标口径消歧。
- SEC/companyfacts/10-K evidence grounding。
- 公式计算和 numeric verifier。
- 不可得/错误前提识别。

可以举三个例子：

### 例 1：Chevron revenue 口径

问题：

> What was Chevron's total revenues for fiscal year 2024?

容易错的答案：

> `$202.792B Total Revenues and Other Income`

Holo 修复后的答案：

> `$193.414B Sales and other operating revenues`

讲法：

> 这说明 Holo 不只是找最大数字，而是在比较报表 line item、SEC concept 和问题口径。

### 例 2：NVIDIA Data Center revenue

问题：

> What was NVIDIA's Data Center segment revenue for fiscal year 2024?

关键点：

- gold 里有 excerpt-limited `NOT_AVAILABLE`。
- Holo live retrieval 找到更完整真实答案 `$47.5B`。
- 这说明系统不只是复述给定 excerpt，而能通过工具扩展证据。

讲法：

> 这里体现了 agent 的价值：当原始片段不足时，它能查更完整来源，并给出 source-grounded actual answer。

### 例 3：FinanceBench fixed asset turnover

问题类型：

- 不是单点 lookup。
- 需要 revenue、FY2018 PP&E、FY2019 PP&E、average PP&E、ratio。

讲法：

> 这个案例展示 Holo 的完整 workflow：检索 -> 抽取 -> slot filling -> transform plan -> calculator -> verifier -> cited final answer。

## 6. 当前 benchmark 结果

建议用这一页表：

| Benchmark / Run | Result | Meaning |
| --- | --- | --- |
| Historical full40 previous failures | `12/12` | 过去失败项已成稳定回归 |
| Failure regression full11 | `11/11` | 年度口径、收入口径、NR 类修复有效 |
| FinAgent full40 live strict | `38/40 = 95.0%` | 完整 live 40 题严格分 |
| FinAgent full40 rescored | `39/40 = 97.5%` | 合理不可得/纠正答案计入后 |
| FE_020 post-fix live | `1/1` | Chevron 收入口径修复被 live 验证 |

讲法：

> 我们不只录了 demo，还跑了 live benchmark。gold 没有进入 prompt。分数来自 agent 实际调用模型、检索、抽取和合成之后的 post-run scoring。

保守说明：

> 这些结果证明 Kernel v3 在财报事实和指标消歧上已经有强能力，但还不能宣称解决所有金融 benchmark。更复杂的 DCF/LBO、PDF 表格和长链研究还在开发中。

## 7. 这几个月没有白干的证据

可以按工程层次讲：

1. **Architecture**：Kernel v3 从旧 stage line 独立出来。
2. **Agent Loop**：不是单轮 chat，有完整 loop 和停止/修复机制。
3. **Tools**：retrieval、calculator、memory、workspace 都有标准接口。
4. **Evidence**：有 ClaimLedger、SlotFrame、TransformPlan、VerifierGate。
5. **Finance**：能做 SEC fact extraction、metric disambiguation、formula trace。
6. **Demo**：Windows 浏览器可观察 WSL 主脑运行。
7. **Benchmarks**：有 live 分数，不是离线演示。

建议讲法：

> 这几个月最重要的成果不是某个单点功能，而是 Holo 已经具备了一个智能工作系统的骨架。金融只是第一块被打磨到可以演示和评测的领域。

## 8. 用户建议如何被采纳

可以诚实讲：

> 用户提出的方向是 agent loop 并行化、上下文压缩和工具链强化。当前已经采纳了其中一部分。

已完成：

- benchmark 题目级并行。
- compact repair packet。
- finance fact ledger。
- model-owned semantic judgment。
- standardized tool interface。
- live benchmark loop。

未完成：

- 单题内部并行搜索。
- 多假设分支竞争。
- 自动记忆失败模式并复用。
- 大规模几百题统计。

讲法：

> 所以下一步不是再写更多 prompt，而是把 agent loop 从线性工作流升级成并行搜索和压缩推理工作流。

## 9. 当前不足和风险

必须诚实说：

- full40 虽然高分，但平均成本仍高。
- verifier gate pass rate 还不够高。
- 有些题答案对，但证据支持链不干净。
- 单题内部并行化还没完成。
- 更复杂 FinanceBench/FAB/FinQA 还没全面攻克。

建议讲法：

> 这些不是失败，而是下一阶段研究方向。我们已经证明了系统可以通过 LLM + tools + host verification 做真实金融题，下一步要让它更快、更稳、更能泛化。

## 10. 结尾

建议结尾稿：

> Holo Kernel v3 现在已经不是一个概念模型。它可以接收金融问题，调用工具，读取来源，组织证据，完成计算，接受 verifier 检查，并给出带引用的答案。当前最强证据是 live benchmark：历史失败集 12/12，full40 严格 95%，合理重评 97.5%。  
>
> 这说明我们的工作没有停留在演示 UI，而是在构建一个真正的高智力 agent harness。未来的核心方向是把 agent loop 并行化、压缩上下文、强化记忆，让 Holo 从金融专长继续扩展到数学、物理、代码和研究任务。

## 可能被问到的问题

### Q1：这是不是靠规则打表？

答：

> 不是。benchmark gold 不进入 prompt。host 有确定性验证和候选排序，但最终口径选择由 LLM 完成。确定性逻辑用于证据抽取、权限、citation、numeric support 和 post-run scoring，不是答案表。

### Q2：Holo 和 ChatGPT 的区别是什么？

答：

> ChatGPT 通常给最终文本。Holo 的重点是 agent harness：工具调用、证据组织、日志、verifier、calculator、长期状态和可视化。它不是只追求生成一个答案，而是追求可审计的工作过程。

### Q3：现在能做哪些金融题？

答：

> 当前最稳的是 SEC/10-K/companyfacts 上的事实抽取、收入/利润/资产/现金流等口径消歧、简单到中等公式计算、错误前提识别。复杂估值、DCF/LBO、多文档研究、PDF 表格和长链报告仍在强化。

### Q4：为什么 full40 不是 100%？

答：

> 原始严格分是 95%，主要问题来自口径和 scoring mismatch。FE_020 已 live 修复；FE_034 是 excerpt-limited gold 与 live retrieval 找到真实完整答案之间的冲突。系统仍需要 clean rerun 和更强 verifier/synthesis consistency。

### Q5：下一阶段最关键技术是什么？

答：

> 单题内部并行 agent loop。让模型提出多个检索/计算假设，host 并行执行工具分支，再让模型比较证据并收敛。这会同时提升速度、搜索覆盖和鲁棒性。

