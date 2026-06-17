# Kernel v3 Debug50 需求归纳与通用金融 Agent Loop

记录时间：2026-06-17 CST +0800  
分支：`kernel-v3`  
状态：架构复盘与通用 loop 设计；未启动 live 刷题。

## 0. 边界

本次只读 `data/bench/finance/financebench_doc_retrieval.jsonl` 前 50 行的题面和公开元数据，用于分析任务类型和工具需求。

没有读取或使用 `gold_answer` / reference evidence 来生成答案、调参或汇报能力。本文不是 benchmark accuracy 报告；FinanceBench/FQA/FAB 能力进展仍只允许来自 live model/live retrieval 运行，并且 gold/reference 只在完成后评分使用。

## 1. 为什么不能逐题补

第三题 3M FY2022 capital-intensive 做不出，不是单题公式缺失，而是系统结构暴露了更深问题：

```text
题目需要：
  多个 filing facts -> 多个 ratios -> 业务语境判断 -> 引用和验证

当前容易变成：
  retrieval.run 一次性吞掉检索/抽取/绑定/判断
  或 host formula scaffold 被迫救场
  失败时 loop 只看到粗 observation，难以按缺口重规划
```

因此后续不能继续“一题一个补丁”。正确优化单位应是任务族闭包：每类题都必须能稳定进入同一个通用 loop，并能临时组装工具工作台。

## 2. Debug50 任务族

这 50 题不是单一“查一个数”。它们覆盖至少五个重叠任务族：

| 任务族 | 行数 | 核心要求 | 典型例子 |
| --- | ---: | --- | --- |
| 直接行项目或披露抽取 | 18 | 找到权威文档/报表/披露段落，绑定单位、期间、引用 | capex、net PP&E、inventories、debt securities、major acquisitions |
| 定义公式数值计算 | 13 | 多槽取证，按题面公式计算，保留 FormulaTrace | fixed asset turnover、DPO、ROA、OCF ratio、3-year average margin |
| 计算后业务判断 | 11 | 算 ratio/trend 后由 LLM 做金融语义判断，不能靠硬阈值 | capital-intensive、quick ratio health、operating/gross margin profile、positive working capital |
| 驱动归因/调整项 bridge | 6 | 找 MD&A 或 reconciliation/bridge 表，识别排除项和 driver | excluding M&A segment drag、real sales change excluding FX/pass-through/one-off、margin change drivers |
| 表格排序/比较 | 4 | 抽完整表，归一化行列，排序/比较，再映射回 cited row | largest liability、cash flow activity with most inflow/lost least、segment proportional increase |

这些是重叠分类；例如 inventory turnover 既是公式计算，也带“库存管理是否有意义”的业务判断。

## 3. 对工具链的要求

每类题需要的工具不是固定答案规则，而是可组合 primitive：

- Source acquisition: `retrieval.run`, `sec.edgar.company_filings`, issuer IR/SEC URL binding.
- Structured filing facts: `sec.edgar.financials`, SEC/XBRL facts, company filings.
- Document/table extraction: `document.docling.convert`, `document.trafilatura.extract`, local cached artifacts.
- Table operations: `data.table.query`, `script.exec` for temporary parser/normalizer.
- Arithmetic: `calculator.compute`, `math.sympy.compute` for harder symbolic/high precision work.
- Provenance: `ClaimLedger`, `FinanceFactLedger`, `CitationItem`, `FormulaTrace`.
- Verification: `finance.verify_numeric`, synthesis gate, source URL/citation gate.
- Working state: compact `TaskSpec`, `EvidenceSpec`, `TransformSpec`, `SlotFrame`, missing slots, previous failures.

## 4. 当前架构缺口

当前系统已经有 LangGraph-backed loop、ToolRegistry、PolicyGate、journal、tool surface、Docling/OpenBB isolated workers、FactLedger/ClaimLedger/FormulaTrace 等组件，但组合方式仍有明显缺口：

1. `retrieval.run` 太粗，容易把 source acquisition、evidence extraction、table parsing、slot binding 和 synthesis 前置混在一起。
2. `finance_fact_ledger`、`slot_frame`、`transform_plan`、`finance_slot_bind` 主要在 finalization/preflight 内部生成，不够像 agent loop 的一等工作台状态。
3. LLM 能看到工具名，但必须更明确看到通用 loop：任务编译、取证、绑定、计算、判断、验证/重规划。
4. finance-capability 下 host semantic fallback 已禁用，这是正确的；但部分 formula/retrieval scaffold 仍容易形成逐题补丁心智。
5. 可恢复工具失败应成为下一轮 planner 的结构化 observation，不能导致粗糙失败或阻塞在内部 workbench 模型调用。

## 5. 通用 Finance Agent Loop

通用 loop 应为：

```text
Task Compile
  LLM -> TaskSpec / EvidenceSpec / TransformSpec / SlotFrame
  Host -> schema validation + journal

Evidence Acquire
  LLM -> retrieval / SEC / document / table tool choice
  Host -> policy + network budget + artifacts + citations

Ledger Bind
  LLM -> which facts fill which slots, period basis, line-item basis
  Host -> validate fact ids and provenance, record ClaimLedger/FinanceFactLedger/SlotFill

Transform Compute
  LLM -> formula expression, variables, fact ids, unit, rounding
  Host -> calculator/data.table execution, FormulaTrace

Semantic Synthesis
  LLM -> answer judgment, comparison/trend/business explanation
  Host -> no unsupported claims, citation and synthesis gate

Verify Or Replan
  Host -> numeric/provenance diagnostics
  LLM -> repair answer, fetch more evidence, choose alternative tool, or finalize
```

这个 loop 解决的是“所有 FB/FQA 题型理论上可进入同一个工作台”的问题，而不是某题答案。

## 6. 系统合同覆盖检查

这里的“理论上能做”定义为：题目可以被合同表达成可执行状态机，并且每个状态都有模型可见接口、host 执行边界、observation 反馈和终止/重规划条件。

| Debug50 任务族 | TaskSpec/EvidenceSpec | TransformSpec | 工具入口 | 状态反馈 | 理论覆盖 |
| --- | --- | --- | --- | --- | --- |
| 直接行项目或披露抽取 | entity、period、source、statement/section、line item/disclosure slot | 通常 not_applicable 或 identity transform | retrieval/SEC/document extraction | evidence/citation/claim ledger/slot fill | covered |
| 定义公式数值计算 | input slots、period basis、source family、unit/scale | calculator expression、output unit、required slots | SEC/document/table/calculator/verifier | fact ledger、FormulaTrace、numeric verification | covered |
| 计算后业务判断 | quantitative slots + qualitative/business context slots | ratio/trend transform；无硬阈值 | retrieval/SEC/calculator/verifier | computed ratios + cited context + synthesis gate | covered |
| 驱动归因/bridge adjustment | MD&A/reconciliation/table driver slots、exclusion slots | subtotal/change/ranking transform when needed | document/table/data.table/query/calculator | driver evidence、bridge rows、formula traces | covered |
| 表格排序/比较 | table rows、category key、period, metric slot | max/min/rank/aggregate transform | docling/table query/script/calculator | normalized table artifact、row-level citation | covered |

逐行看，前 50 题都落入这些任务族之一或多个交集，因此从系统合同角度是 `50/50 contract-covered`。这不是 live accuracy，也不是 gold-based evaluation；它只说明没有某一类题被排除在 ABI、工具、状态或 verifier 之外。

系统合同必须保持四个硬条件：

1. LLM 看得见 `finance_agent_loop_contract`、工具目录和当前 working state。
2. Host 只验证 schema/policy/budget/provenance/arithmetic，不替模型决定财务语义。
3. 每个工具失败都是结构化 observation，除 policy/safety/budget 外应允许重规划。
4. 最终答案必须通过 citation / FormulaTrace / numeric verification / synthesis gate，或明确说明证据缺口。

当前接口 preflight 结果：

```text
Finance tool readiness: ok
execution_profile=finance-capability runtime_backend=langgraph live_network_budget=True
allowed_tools=17 provider_tool_selection=17 planner_prompt_tool_selection=17

Required categories:
- financebench_filing_retrieval: interface=ok components=ok
- financebench_filing_table_extraction: interface=ok components=ok
- financebench_numeric_ratio_reasoning: interface=ok components=ok
- financebench_market_or_macro_context: interface=ok components=ok
- finqa_report_context_numeric_reasoning: interface=ok components=ok
- finqa_table_program_like_transforms: interface=ok components=ok
- temporary_workbench_assembly: interface=ok components=ok

capability_claim=false; benchmark_progress_claim=false
```

这条检查只证明系统合同和工具入口可用，不证明 FinanceBench/FQA 准确率。

## 7. 本次落地

本次已把 generic finance loop contract 加入模型可见工具面：

- `kernel_v3/finance/tool_catalog.py`
  - 新增 `FINANCE_AGENT_LOOP_CONTRACT_SCHEMA`。
  - 新增 `finance_agent_loop_contract()`。
  - 合同包含六阶段 loop、状态对象、五类通用任务族 workflow、stop invariants。
  - 合同不含 debug50 行号、FinanceBench id、gold/reference 或答案规则。

- `kernel_v3/finance/open_components.py`
  - `finance.toolchain.describe` 返回 `agent_loop_contract`。

- `kernel_v3/agent/runtime.py`
  - finance-capability planner directive 首包携带 `finance_agent_loop_contract`。
  - runtime compact 保留该 contract 的阶段、状态对象、任务族和 stop invariants。
  - `finance_working_state` 现在暴露 recipe/model 编译出的 `execution_program`、当前 phase、missing slots、fact/formula/verifier presence。
  - retrieval observation 后，evaluator 会把可解析数值证据写入 `finance_fact_ledger` / `claim_ledger`；如果是非数值披露/MD&A 证据，则写入 source-grounded `claim_ledger`，供下一轮 planner 继续绑定和重规划。
  - 如果存在 `TransformSpec` 且已有证据但还没有 `FormulaTrace`，evaluator 会返回 `continue`，要求模型进入 calculator/table transform，而不是提前 final。
  - 新增模型可调用工具 `finance.slot_bind`：LLM 提交 `slot_bindings`、`period_basis`、`line_item_basis` 和 `formula_requests`，host 只校验 fact ids / schema，并返回 calculator-ready payload。

- `kernel_v3/processors/adapters.py`
  - provider compact 也保留 `finance_agent_loop_contract`，避免“本地 state 有、真实发包无”。

这一步不是最终通用 loop，只是把 loop contract 提升为模型真实可见的稳定 ABI。下一步应把 ledger bind / task compile / table extraction 从 finalizer 内部继续前移为 loop 中可观察、可恢复的一等步骤。

## 8. 下一步优先级

已推进：

1. `task.compile` / recipe `execution_program` 现在进入 `finance_working_state.execution_program`，不再只作为 `agent_replan_hints` 的旁路提示。
2. `finance_working_state.workbench` 现在给出 `current_phase`、missing slots、transform spec count、facts/traces counts 和下一步候选；这只是状态提示，LLM 仍决定下一步工具和金融判断。
3. `_AgentContextCompiler` 在没有任何 ledger/facts 的第一轮，也能把 recipe execution program 暴露成 `evidence_acquire` 工作台状态。
4. `_RecipeEvaluator` 在 retrieval answer 路径下，如果模型直接 `respond` 但 finance workbench 仍有 missing slots 且 verifier 未通过，会返回 `continue` 和缺槽反馈，而不是把失败推迟到 finalizer 的 `missing_retrieval_report`。
5. retrieval tool observation 完成后，`_RecipeEvaluator` 会即时构建 loop workbench 用的 `finance_fact_ledger` 和 `claim_ledger`；公式/行项目题能看到 candidate facts，披露/驱动归因题能看到 source-grounded candidate claims。
6. 对带 `TransformSpec` 的公式题，如果证据已到但没有 `FormulaTrace`，evaluator 会返回 `finance_execution_program_transform_required`，把 loop 推到 deterministic transform 阶段。
7. `finance_working_state` 现在纳入 compact `claims` / `claim_ledger_count` / `claim_count` / `presence.claim_ledger`，避免非数值题只停留在 retrieval report 里。
8. `finance.slot_bind` 已成为 planner/provider 可见工具。它不是 host semantic fallback，而是 LLM one-shot 提交绑定结果的 ABI；host 只做 fact id 校验、schema 校验和 calculator payload 准备。
9. `finance_working_state` 能读取 `tool:finance.slot_bind` observation，把 slot binding basis、accepted formula plan count 等状态暴露给下一轮 planner。

仍需继续：

1. 把 `document -> table -> data.table.query` 做成稳定链路，减少全文 span 搜索承担表格推理。
2. 禁止内部 workbench 模型调用无 deadline 地阻塞主 loop；任何工具/processor failure 必须结构化返回 observation。
3. 等通用 loop 闭环后，再按任务族跑 debug50 live，不再按单题刷。
