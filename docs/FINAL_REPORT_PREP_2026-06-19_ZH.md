# Holo Kernel v4 最终报告准备稿

日期：2026-06-19

分支：`kernel-v4`

状态：成熟版本检查点。当前暂停继续测试，进入最终报告材料整理、实验数据归档和系统发展脉络梳理阶段。

## 一句话定位

Holo Kernel v4 是一个面向复杂金融研究任务的通用单 Agent harness。系统目标不是把 FinanceBench 题目写成规则表，而是构建一个稳定的模型驱动行动闭环：LLM 自主理解任务、发现和调用工具、读取证据、计算核验、形成答案；host 负责验证工具协议、执行工具、记录事件、管理上下文和保护安全边界。

## 与课程要求的对应关系

课程要求强调从 AI 工具使用者转向科研系统构建者，项目需要体现真实问题、Agent 系统链路、工具调用、评测、失败分析和边界讨论。Holo 的对应关系如下：

| 课程要求 | 本项目对应内容 |
| --- | --- |
| 真实问题 | 金融基本面研究和公开财报问答需要证据检索、表格理解、数值计算、公式选择和业务解释，不是一次普通 LLM 调用能稳定解决的任务。 |
| Agent 主线 | Kernel v4 建立 `input -> understand -> decide -> act/tool -> observe -> verify -> final answer` 的闭环。 |
| 技术复杂性 | 单 Agent loop、provider-native tool calling、streaming tool executor、artifact lifecycle、tool discovery、SEC/EDGAR/document/table/calculator/numeric verifier 工具面。 |
| 数据与评测 | FinanceBench public-filing tasks；gold/reference 只在每题完成后评分，不进入模型上下文。 |
| 实验 | debug50、replay、strict remaining offsets；记录 pass/fail、turns、tool calls、token usage、cache hit、cost、failure reasons。 |
| 失败分析 | 主要失败集中在 numeric tolerance、final-answer completeness、empty final answer、长题成本。 |
| 边界与伦理 | 不泄露 benchmark gold，不用 fake test 做能力证明，不做答案打表；金融输出应被视为研究辅助，不构成投资建议。 |

## 从项目建议书到最终系统

项目建议书中提出 Holo 的目标是搭建完整 Agent 行动闭环基座，并特化用于金融基本面研究。最初设想包括用户输入、短期记忆、长期记忆、检索工具、本地数据脚本、系统推理和 Agent loop 反馈。

实际迭代后，项目重点收敛为：

1. 放弃 v3 中过重的金融语义闸门，重写一个通用单 Agent loop。
2. 参考成熟开源 Agent 项目的核心思想：streaming tool execution、tool-use context、tool result lifecycle、tool discovery、abort/cancel、context edit。
3. 将金融能力作为工具链和 prompt contract 暴露给模型，而不是由 host 打表或强行补槽。
4. 用 live benchmark 结果证明系统真实做题能力，并记录失败类型和成本。

这条路线和建议书目标一致：Holo 的核心贡献不是一个静态金融问答脚本，而是一个可扩展的 LLM harness 基座。

## 系统架构

### 核心循环

Kernel v4 的主循环由以下组件组成：

- `SingleAgentLoop`：单 Agent 行动循环，控制 turn、预算、finalization 和异常退出。
- `OpenAICompatibleChatProvider` / `DeepSeekChatProvider`：把工具暴露成 provider-native function tools，并解析流式 tool-call delta。
- `StreamingToolExecutor`：模型流式输出工具调用后，host 立即执行工具并记录生命周期。
- `ToolUseContext`：保存 messages、metadata、artifacts、workflow context、in-progress tool ids。
- `WorkflowObserver`：实时暴露 `model_start`、`assistant_tool_call`、`tool_start`、`tool_result`、`loop_completed/failed` 等事件。
- `artifact.inspect/search/read`：把大文档和大工具结果转成可检索、可窗口读取的 artifact。
- `tool.discovery` / `finance.workbench.open`：让模型按任务需要发现工具族和金融工作台，而不是把所有工具逻辑写死在 host。

### 金融工具面

当前金融能力主要来自：

- SEC/EDGAR filing discovery and document expansion
- company filing/document extraction
- artifact search/read
- provided context parser for FQA/FinQA-style rows
- table query and transform
- calculator and SymPy computation
- fiscal date/day-count utility
- numeric verifier
- finance workbench profiles for inventory efficiency, gross margin, working capital, capital intensity, legal proceedings, shareholder vote results, cash-flow conversion, multi-company comparison 等

host 不预先计算 benchmark 答案；LLM 决定证据、公式和工具调用。host 只执行、记录、约束工具协议，并在最终答案前提示数值核验和覆盖检查。

## 关键实验协议

硬约束：

- live tests 才能作为金融能力证据。
- fake/offline tests 只能作为结构、schema、compile 或 safety regression，不能作为做题能力证据。
- gold/reference/scoring material 不进入模型上下文。
- 不使用答案表、题目打表或 hard-coded benchmark rule。
- debug 和 test 必须区分；被人工分析过的题不能再当 clean held-out test。

当前有效实验材料分三类：

| 类型 | 说明 | 是否可当最终 clean test |
| --- | --- | --- |
| debug50 | offsets `0-49`，用于系统调试和能力建设。最佳记录 `50/50` live pass。 | 否 |
| replay / inspected stream | 已用于失败分析或系统修复的题，包括 offsets `50-95` 和 replay failure offsets。 | 否 |
| strict remaining offsets | offsets `96-149`，本轮冻结配置 live strict 分块跑完，共 `54` 道。 | 可以作为剩余 untouched pool 的严格证据，但不是完整 100 题测试。 |

## 当前成熟版本关键数据

### 结构回归

最近一次结构/回归检查：

```text
.venv/bin/python -m pytest tests/test_kernel_v4_finance_eval.py tests/test_kernel_v4_single_agent_loop.py tests/test_kernel_v4_finance_runner.py tests/test_kernel_v4_finance_score.py -q
119 passed in 3.65s
```

说明：这是结构正确性证据，不是金融 benchmark 能力证据。

### Replay failure recovery

早期 replay failure offsets 经过通用 loop/tool/prompt 修复后，已有单题或稀疏 live pass 证据：

```text
53, 60, 62, 73, 75, 76, 77, 80, 94
```

其中 offset `77` 的关键修复是：calculation checkpoint 不能过早关闭本地证据工具，必须保留 `artifact.search/read` 和 `document.text.extract`，否则模型在法律事项类问题上无法继续读取精确证据。

### Strict remaining offsets 96-149

聚合文件：

```text
.state/kernel_v4/bench/finance/fb_strict_o096_o149_aggregate_v39_20260619/summary.json
```

配置：

| 配置项 | 值 |
| --- | --- |
| model | `deepseek-v4-flash` |
| thinking | `enabled` |
| reasoning effort | `low` |
| model context mode | `off` |
| max turns | `160` |
| max tool calls | `420` |
| max tool result chars | `12000` |
| per-item timeout | `1800s` |
| gold/reference | scoring-only, not in model context |

结果：

| 指标 | 数值 |
| --- | ---: |
| item count | 54 |
| passed | 42 |
| failed | 12 |
| pass rate | 77.78% |
| run failed | 1 |
| numeric tolerance failures | 11 |
| source-grounded qualitative failures | 1 |
| aggregate cache hit rate | 89.06% |
| estimated total cost | `$1.4435` |
| total tokens | 74,549,175 |
| mean turns | 31.80 |
| median turns | 24.5 |
| max turns | 136 |
| mean tool calls | 34.06 |
| median tool calls | 26 |
| max tool calls | 135 |
| mean duration | 139.45s |
| max duration | 444.67s |

失败 offsets：

```text
105, 106, 111, 118, 121, 122, 127, 133, 138, 139, 140, 141
```

run-level failure：

```text
121: empty_final_answer
```

高成本长题：

```text
97, 143: >= 5M total tokens
97: 96 turns / 112 tools
143: 136 turns / 135 tools
```

长循环样本：

```text
97, 98, 131, 132, 137, 142, 143
```

这些样本适合在报告中展示“系统能做复杂长任务，但成本和收敛效率仍是主要瓶颈”。

## 失败类型归因

当前失败不是工具链完全断裂，而是更上层的金融推理和最终答案稳定性问题：

1. 数值 tolerance 失败：多数失败来自提取数值、选择公式口径、单位/符号/期间处理或 final answer completeness。
2. 空最终答案：offset `121` 显示 loop 在长推理后仍可能进入 `empty_final_answer`，需要更强的 finalization recovery。
3. 长题成本：offset `143` 虽然通过，但消耗 `11.1M` tokens，说明 artifact 搜索、重复取证和 endgame 收敛仍有优化空间。
4. 工具调用冗余：部分题在已有证据足够后仍继续检索，说明“证据充分性判断”和“停止条件”仍依赖模型能力和 prompt contract。
5. Numeric verifier 覆盖不足：验证工具能检查显式数字，但不能替代模型对所有 required facts 是否齐全的判断。

## Agent loop 和通用能力还能优化什么

下面是下一阶段架构优化方向，均应保持 LLM 决策为核心，避免回到规则打表。

### 1. Finalization reliability

目标：减少 `empty_final_answer`、工具 markup final answer、以及“证据已足够但答非所问”。

可做：

- final answer draft -> self-audit -> final answer 的两步模型内流程。
- no-tools finalization turn 上保留更明确的 answer schema contract。
- 对自指回答、过程性回答、空回答继续做通用 recovery。
- 将 required facts checklist 作为模型可见任务合同，而不是 host 代填答案。

### 2. Numeric precision and unit discipline

目标：降低 numeric tolerance failure。

可做：

- 对所有 material numeric claims 强制使用 calculator/verifier。
- final answer 必须同时写出 source line item、period、unit、formula、substitution。
- ratios/margins/returns 同时给 decimal 和 percentage；change 同时给 absolute change 和 percentage-point change。
- 对平均值、期末值、同比、财年天数、currency unit 做 explicit basis statement。

### 3. Evidence sufficiency control

目标：减少“证据不足时过早回答”和“证据足够后继续乱搜”。

可做：

- 让模型维护轻量 task checklist：facts acquired / formulas verified / answer coverage。
- artifact search/read 工具返回更清晰的 section/title/page metadata，帮助模型定位证据。
- source saturation checkpoint 继续只收窄工具面，不替模型判断答案。

### 4. Cost and cache optimization

目标：保持高 cache hit，同时降低长题 token 爆炸。

现状：

- strict54 aggregate cache hit rate 已达 `89.06%`。
- 个别长题仍超 `5M` tokens。

可做：

- 稳定 system prompt 和 tool schema，避免高频变动破坏 cache。
- 减少每轮 transient context，保持 `model_context_mode=off` 作为默认。
- 将大 evidence 放在 artifact 中，通过窗口读取和 snippets 返回。
- 做 run trace compaction：保留事实、来源、工具结果摘要，压缩重复工具调用历史。

### 5. Tool discovery and workbench maturity

目标：让模型 one-shot 更好地知道可用工具和调用方式。

可做：

- `finance.workbench.open` 输出更短但更结构化的 task-family contract。
- 工具 schema description 更贴近模型调用意图。
- 对 high-value 工具提供 examples，但不包含 benchmark 答案。
- deferred tools 根据 task family 动态展开，减少初始 tool surface 噪声。

### 6. Reportable process observability

目标：把 agent 工作流做成可展示、可复现实验材料。

可做：

- 保存 workflow event timeline。
- 为每题记录 `turns/tools/tokens/cache/cost/pass/fail reason`。
- 生成图表：pass rate by segment、cost distribution、turn/tool scatter、cache hit distribution、failure taxonomy。
- 用 2-3 个典型 case 展示 Agent 如何从题面到证据、工具、计算、核验、最终答案。

## 最终报告建议结构

使用课程模板 `D:\COURSES\人工智能算法实践\上海交通大学课程大作业模板`。

建议章节：

1. 摘要
   - 金融研究 Agent 的问题定义。
   - Kernel v4 方法。
   - 关键结果：debug50 best-recorded pass、strict54 `42/54` live pass、cache/cost/失败类型。
2. 引言
   - 为什么金融财报问答需要 Agent 系统。
   - 一次 LLM 调用的不足：证据、工具、计算、核验、长上下文。
   - 本项目贡献。
3. 相关工作
   - Agent loop / tool calling / ReAct / function calling。
   - Financial QA / FinanceBench / FinQA。
   - RAG、artifact/document processing、numeric verification。
4. 数据与任务
   - FinanceBench public filings。
   - debug/test/replay split policy。
   - gold/reference 隔离原则。
5. 方法
   - Kernel v4 single-agent loop。
   - 工具链和 artifact lifecycle。
   - Finance workbench and no-gold task packet。
   - Numeric verification and finalization checkpoints。
6. 实验设置
   - 模型、thinking、max turns/tools、provider、cost estimation。
   - 结构测试和 live benchmark 的区别。
7. 实验结果
   - debug50 development result。
   - replay recovery result。
   - strict remaining 54 result。
   - cache/cost/turn/tool statistics。
8. 消融与分析
   - model_context_mode/cache。
   - thinking disabled/low/medium repeat probe。
   - long-tail cases 97/143。
9. 失败分析
   - numeric tolerance。
   - empty final answer。
   - over-search and high cost。
   - remaining generality limits。
10. 总结与未来工作
   - 当前成熟度。
   - 还需要 fresh held-out 100-question split。
   - 通用 Agent harness 可迁移到数学、物理、科研文献等领域。

## 建议图表

报告中至少需要这些图表：

| 图表 | 数据来源 |
| --- | --- |
| Kernel v4 architecture diagram | 根据 `kernel_v4/loop.py`, `tooling.py`, `context.py`, `finance_runner.py` 绘制。 |
| Agent workflow sequence | workflow events: model_start -> tool_call -> tool_result -> verify -> final. |
| Strict54 pass/fail bar | aggregate summary。 |
| Failure taxonomy pie/bar | `failure_reasons`。 |
| Turns vs tool calls scatter | `items.jsonl`。 |
| Total tokens distribution | `items.jsonl`。 |
| Cache hit rate distribution | item usage summaries。 |
| Cost by item | item cost estimates。 |

## 报告写作口径

可以说：

- “Kernel v4 已经形成成熟单 Agent loop 和金融工具链。”
- “FinanceBench debug50 是开发/调试集合，最佳记录为 50/50 live pass。”
- “剩余未用于调试的 offsets 96-149 共 54 道，冻结配置 live strict 结果为 42/54，pass rate 77.78%。”
- “gold/reference 未进入模型上下文。”
- “失败主要集中于数值精度和 finalization，而不是工具链完全不可用。”

不能说：

- “已经完成 clean test100 77%/80%/90%。”
- “debug50 结果代表泛化测试准确率。”
- “replay 题目是 held-out test。”
- “结构测试 passed 等于金融做题能力。”

## 当前版本保存建议

当前版本应作为 `kernel-v4` mature checkpoint 保存。建议提交内容包括：

- `kernel_v4/` 当前 loop、provider、finance runner、tools、score/eval/repeat/ablation 代码。
- `tests/test_kernel_v4_*` 结构回归。
- `README.md` 和本报告准备文档。
- 不提交 `.state/` 大量 live run artifacts；只在文档中引用路径和关键统计。
- 如需长期保存实验数据，可后续单独打包 summary-only artifacts 或放入外部补充材料。

