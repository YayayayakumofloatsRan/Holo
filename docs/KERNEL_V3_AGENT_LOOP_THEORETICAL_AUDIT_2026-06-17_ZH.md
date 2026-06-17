# Kernel v3 Agent Loop 理论能力审查

记录时间：2026-06-17 CST +0800  
分支：`kernel-v3`  
状态：严格架构审查；本文不记录 live benchmark 分数，不作为提交/推送说明。

## 0. 审查目标

本次审查的目标不是证明系统已经“刷过”FinanceBench 或 FinQA，而是判断当前
agent loop 和工具接口是否具备理论上解决这两类任务全集的结构条件：

- FinanceBench：公开金融 filing/source-grounded QA。核心难点是源定位、文档/表格抽取、精确行项目绑定、公式计算、定性金融解释、引用和 gold 隔离。
- FinQA：给定报告文本和表格的数值推理。核心难点是表格结构理解、文本-table slot binding、多步公式/程序推理、计算 trace 和最终数值支持。

系统应满足的高层命题：

```text
LLM sees a stable one-shot action ABI
  -> LLM chooses task decomposition/source/tool/formula/final readiness
  -> host validates schema/policy/budget/provenance
  -> host executes tools and records Observation/Artifact/Trace
  -> next LLM step receives compact state and can replan
  -> final answer is citation/formula/verifier gated
  -> benchmark gold/reference never enters runtime context
```

## 1. 当前 Agent Loop 主路径

当前 finance-capability 路径是：

```text
AgentRuntime.run
  -> semantic intake / task graph / answer profile
  -> TaskRecipe(retrieval_answer)
  -> optional model-first task.compile
  -> ToolRegistry with finance toolchain
  -> ModelPlanner wrapped by _RecipeBoundPlanner
  -> LangGraphLoopController
      node prepare_and_execute:
        ContextCompiler -> planner.propose -> PolicyGate -> ToolRegistry
        -> Observation + Artifact journal
      node evaluate_and_route:
        post-observation ContextCompiler -> ModelEvaluator/_RecipeEvaluator/WorkloopEvaluator
        -> continue / terminal
  -> retrieval synthesizer / numeric verifier / final gate
```

LangGraph 已经是 finance/web/long profile 的 active backend。Holo 仍保留硬边界：

- `PolicyGate`：权限、side effect、tool enablement。
- `ToolRegistry`：manifest schema、payload canonicalization、tool execution。
- Journal/Artifact：每步 context/action/policy/observation/feedback/result 可审计。
- Budget guard：step/tool/network/artifact 上限。
- Finance verifier：FormulaTrace、NumericVerification、synthesis gate。
- Benchmark runner：post-run scoring；gold/reference 不进入 prompt/tool/retrieval/memory。

## 2. One-shot ABI 审查

一个可写论文的 agent loop 必须有稳定 ABI，而不是靠隐式 prompt 约定。当前 ABI 已有明确层次。

### 2.1 Planner JSON schema

`planner.propose` 输出固定为：

```json
{
  "action_id": "stable id",
  "kind": "respond|tool|ask_user",
  "name": "registered tool name or null",
  "description": "why this action",
  "payload": {},
  "score": 0.0,
  "reasons": [],
  "side_effect_class": "none|read|write|destructive|shell|network"
}
```

host 只接受 `respond/tool/ask_user`，tool 名必须在 allowlist 中。

### 2.2 Provider-visible tool surface

实际 packet 检查显示，finance-capability + network budget 下 provider 可见：

```text
retrieval.run
calculator.compute
finance.verify_numeric
finance.toolchain.describe
data.table.query
math.sympy.compute
sec.edgar.company_filings
sec.edgar.financials
document.docling.convert
document.trafilatura.extract
market.openbb.fetch
workspace.list
workspace.search
file.read
workspace.write
shell.exec
script.exec
```

`tool_selection_count = 17`，visible tools 也是 17，说明当前 provider compact 没有再把
tool surface 截断。packet 还携带：

- `llm_first_finance_template.standard_tool_interface`
- `toolchain_install_summary`
- `allowed_tools`
- `forbidden`
- `search_strategy_hint`
- `toolchain_state`
- `finance_working_state`
- `agent_replan_hints`

结论：one-shot 工具可见性这一层当前满足理论要求。

## 3. FinanceBench 理论覆盖

FinanceBench 任务族可以拆成以下能力闭包。

| 能力 | 当前机制 | 审查结论 |
| --- | --- | --- |
| 目标公司/期间/文档识别 | semantic intake、TaskSpec、target document metadata、retrieval payload metadata | 基本满足 |
| 官方源获取 | `retrieval.run`、SEC structured provider、`sec.edgar.*`、direct source URL、Docling/Trafilatura | 基本满足，依赖 live provider 稳定性 |
| filing 文档/表格读取 | retrieval extraction、Docling wrapper、Trafilatura wrapper、script.exec、workspace tools | 理论满足，工程上仍需强化表格结构化 |
| 精确行项目绑定 | model-first `task.compile`、`finance.slot_bind`、FactLedger/ClaimLedger、target binding | 部分满足，仍有规则 scaffold |
| 数值计算 | `calculator.compute`、FormulaTrace、SymPy、script.exec | 满足 |
| 定性金融判断 | LLM owns semantics，host only verifies support | 理论满足 |
| 证据和引用 | EvidenceItem/CitationItem、synthesis gate、required source URL scoring | 基本满足 |
| 失败重规划 | Workloop feedback、retrieval workbench、toolchain_state、recoverable tool failure replan | 基本满足 |
| gold 隔离 | import modes、post-run scoring、annotation policy | 满足 |

FinanceBench 理论上可解的关键在于：不是 host 知道某道题答案，而是 LLM 可以在同一个稳定 ABI 下自由组合：

```text
retrieval.run / sec.edgar.*
  -> document.extract / table query / script parser
  -> FactLedger / slot binding
  -> calculator.compute / sympy
  -> finance.verify_numeric
  -> final synthesis
```

### FinanceBench 当前最大理论缺口

1. `formula_planner.py` 和 retrieval payload augmentation 仍包含较多关键词式公式/检索 scaffold。
   这些不是答案表，但会削弱“LLM 完全拥有语义判断”的论文表述。

2. Docling/OpenBB 属于 wrapper/catalog active，但重组件仍需要隔离 worker 或独立环境。
   若要声称完整 source/document coverage，需要把隔离 worker 接入主 ToolRegistry ABI。

3. filing table extraction 仍偏 retrieval span/text，缺一个稳定的 `document.tables.extract -> data.table.query`
   结构化链路。现在可通过 Docling/script.exec 达成，但接口还不够直接。

## 4. FinQA 理论覆盖

FinQA 与 FinanceBench 不同。FinQA 的主要信息通常已经在题目 context 中，难点不是 live 检索，而是
table/text reasoning。

| 能力 | 当前机制 | 审查结论 |
| --- | --- | --- |
| 给定 context 进入模型 | `oracle_context` prompt_context | 满足 |
| gold/reference program 隔离 | `reference_program_policy=scoring_only_not_prompted` | 满足 |
| 表格/文本证据记录 | benchmark provided context trace、ClaimLedger/SlotFrame | 部分满足 |
| 表格结构化查询 | `data.table.query` 支持 rows/tables/csv_text | 工具满足，但 context 到 rows/tables 的转换不够自动 |
| 多步计算 | `calculator.compute`、`math.sympy.compute`、`script.exec` | 满足 |
| 任意公式合成 | model-first TaskSpec/TransformSpec、planner can call calculator/script | 理论满足 |
| 数值支持验证 | `finance.verify_numeric`、FormulaTrace | 基本满足 |

FinQA 的理论闭包应是：

```text
provided report context
  -> model extracts table/text slots
  -> optional data.table.query for row/column operations
  -> calculator.compute or math.sympy.compute for exact formula
  -> FormulaTrace
  -> verifier/synthesis gate
```

### FinQA 当前最大理论缺口

1. FinQA table 当前主要以 prompt string 形式进入模型；没有稳定自动的
   `provided_context.table -> structured rows/tables artifact -> data.table.query` 接口。

2. 若 LLM 选择 `data.table.query`，它需要自己从 prompt 复制/重构 rows/tables。
   理论上可行，但 one-shot 低摩擦不足，容易在长表上出错。

3. `formula_planner.py` 覆盖很多金融公式，但 FinQA 的 program space 更开放。
   泛化路线应让 LLM 输出 TransformSpec/calculator expression，而不是期待 deterministic
   formula detector 覆盖所有 program pattern。

## 5. “理论上无可挑剔”需要满足的七个不变量

### 5.1 Model-owned semantics

必须成立：

```text
LLM chooses decomposition, source family, evidence slots, formula, and final readiness.
Host never chooses answer facts or final finance conclusion.
```

当前状态：部分满足。finance-capability 下 `_host_semantic_fallbacks_enabled` 被关闭，
这是正确的；但仍有公式/检索 scaffold。可在论文中称为 host affordance，而不是最终语义判断。
后续应把这些 scaffold 迁移为 model task.compile 输出或 diagnostic hints。

### 5.2 Stable action ABI

必须成立：

```text
Every tool is invoked through one JSON action shape.
Every action has manifest schema and side-effect class.
Every observation returns typed status and compact diagnostics.
```

当前状态：满足。

### 5.3 Complete tool affordance

必须成立：

```text
The model sees all relevant tools in the actual provider prompt, not only in runtime metadata.
```

当前状态：满足。provider compact 已保留完整 finance open tool surface。

### 5.4 Typed state feedback

必须成立：

```text
After each observation, the next planner call sees updated toolchain_state,
finance_working_state, replan_hints, retrieval state, and prior failures.
```

当前状态：基本满足。LangGraph node 在 observation journal 后重新 compile evaluator context；
下一轮 planner 也从 journal 读取 compact state。

### 5.5 Tool failure as observation

必须成立：

```text
Recoverable dependency/source/parser/tool failures produce replan feedback,
not premature final failure.
```

当前状态：基本满足。open component failures can replan；policy/budget/security blocks remain terminal.

### 5.6 Evidence/formula/verifier gate

必须成立：

```text
Material numeric answer = evidence-backed facts + FormulaTrace + verifier/synthesis gate.
```

当前状态：基本满足。Calculator/FormulaTrace/NumericVerification 已存在；缺口在任意表格抽取到 facts 的稳定度。

### 5.7 Gold isolation

必须成立：

```text
Gold/reference/reasoning/program is post-run scoring only.
```

当前状态：满足。FinanceBench/FinQA import 明确标记 reference/gold/program scoring-only；
benchmark runner 在 run 后评分。

## 6. 必须补强的研究/工程问题

### P0：FinQA context-to-table ABI

需要新增或完善稳定工具链：

```text
provided_context.parse
  input: raw benchmark/user context
  output: text_blocks, tables[{name, columns, rows}], source refs

data.table.query
  input: tables from context parser
  output: records + query trace
```

这不是做题规则，而是把题目给定表格变成工具可消费的结构化证据。

### P0：LLM TransformSpec 主线化

finance-capability 应以 model-first `task.compile` / `finance.slot_bind` / `TransformSpec`
为主线：

```text
LLM emits transform_specs
host validates transform inputs exist
LLM or host routes calculator.compute
FormulaTrace records result
```

deterministic formula planner 应降级为：

- offline regression scaffold；
- verifier repair hint；
- model unavailable fallback；
- not the primary semantic path。

### P1：Document table extraction chain

FinanceBench 全覆盖需要稳定：

```text
target source URL
  -> document.convert/document.tables.extract
  -> normalized table artifact
  -> data.table.query
  -> evidence facts
```

当前可通过 retrieval snippets、Trafilatura、Docling wrapper、script.exec 达成，但要作为论文系统，需要把这个链条显式化。

### P1：Outer/Inner 双层 LangGraph

当前 LangGraph 是单层 loop controller。论文级系统应拆成：

```text
Outer Finance Research Supervisor
  - controls budget, phase, memory, failure taxonomy
  - chooses whether to launch/resume inner solver
  - inspects verifier failures and persistent mistake memory

Inner Finance Solver Graph
  - one problem instance
  - tool choice / evidence / formula / final gate
```

这样才能自然描述“复杂任务、长时间、多轮重规划、错误学习”。

### P1：Long-horizon profile distinction

finance-capability 是 benchmark lane，不是无限超算 lane。若论文强调理论上可解复杂任务，应明确：

- `finance-capability`：适合 FB/FQA benchmark problem solving；
- `long-mission`：适合超长任务、批量 research、multi-agent/outer supervisor。

### P2：Open component isolation as first-class runtime

Docling/OpenBB/browser 等重组件应通过隔离 worker 暴露同一个 ToolRegistry ABI。
主 Holo 进程只调用工具，不承受依赖污染和内存风险。

## 7. 可写入论文的核心表述

建议表述：

> Holo Kernel v3 treats an LLM not as a free-running shell agent but as a
> proposal engine inside a host-owned state machine. The LLM emits one
> schema-validated action at a time. The host validates policy, executes tools,
> records evidence and formula traces, and returns typed observations. Financial
> reasoning remains model-owned, while provenance, computation, and benchmark
> isolation are host-enforced.

中文表述：

> Kernel v3 的核心不是把金融题写成规则库，而是把 LLM 放进一个可审计、
> 可恢复、工具接口稳定的 host-owned loop。模型负责语义判断和工具选择；
> host 负责执行、验证、记录和隔离。FinanceBench 与 FinQA 的共同点不是题目相同，
> 而是都可以归约为“证据绑定 -> 结构化转换 -> 可验证计算 -> 有引用合成”。

## 8. 当前总评

当前 agent loop 已经具备理论闭包的主体结构：

- LangGraph active loop；
- schema-first planner/evaluator；
- complete provider-visible tool surface；
- host policy/tool/journal/verifier boundary；
- finance task compiler、slot frame、fact/claim ledger、FormulaTrace；
- FinanceBench/FinQA gold isolation；
- recoverable failure replan。

但还不能称为“无可挑剔”。最重要的理论缺口是：

1. FinQA table context 还没有稳定自动结构化为 tool-ready tables；
2. Finance formula/slot semantic 主线仍混有 deterministic scaffold；
3. document table extraction 没有形成独立、稳定、可组合的 graph node；
4. 双层 supervisor/solver graph 尚未完全落地；
5. 重组件隔离 worker 尚未成为一等工具运行时。

因此下一阶段不应继续围绕单题补规则，而应围绕：

```text
stable one-shot ABI
LLM-owned TaskSpec/EvidenceSpec/TransformSpec
context/table/document structured evidence interface
LangGraph outer/inner solver graphs
typed failure memory and verifier repair loop
```

这条路线理论上能覆盖 FinanceBench 和 FinQA 的问题空间，同时保持论文上可辩护的
“LLM 决策、host 验证”边界。
