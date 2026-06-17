# Kernel v3 2026-06-17 开源组件化转向记录

记录时间：2026-06-17 09:29:54 CST +0800  
分支：`kernel-v3`  
状态：架构转向记录。本文用于把 2026-06-17 这个时间点和此前的小步工具修补明确区分开。

## 0. 本次转向的一句话结论

从这一版开始，Kernel v3 的金融能力迭代不再以“继续手写底层
SEC/表格/文档/多 agent 工具补丁”为主线，而转向：

```text
成熟开源组件负责底层工程能力
Holo host-owned harness 负责边界、验证、日志、评测和长期记忆
LLM 继续负责金融语义判断、工具选择、slot binding、公式意图和最终解释
```

这不是放弃 Holo 的 kernel 定位，而是停止把时间消耗在已经有成熟开源组件覆盖的底层能力上。Holo 的研究价值应集中在双层 agent loop、host-owned 验证边界、金融任务泛化、错误学习、长期记忆和严格 live benchmark。

## 1. 为什么这个时间点必须单独记录

2026-06-17 之前，Kernel v3 已经完成了大量金融 substrate 和 benchmark harness 工作：TaskSpec、EvidenceSpec、TransformSpec、FactLedger、ClaimLedger、FormulaTrace、calculator/verifier、SEC/EDGAR 检索、FinanceBench/FAB split 管理和 live-only 纪律。

但当天的 live FinanceBench debug 过程暴露出一个更高层的问题：单项补丁可以修复某一道题或某类行项目可见性，但系统仍可能在下一道题被表格抽取、证据重排、公司事实源选择、margin 口径或继续检索预算卡住。继续沿着“每失败一题就手写一个底层特例”的方式迭代，会把 Kernel v3 拉回规则系统和刷题脚本，违背“重要金融判断交给 LLM，host 做工具和验证”的核心不变量。

因此本次转向的边界是：

- 2026-06-16 的框架文档主要是“参考优秀项目的思想与原则”。
- 2026-06-17 的本记录是“实现路线转向”：底层工具链直接采用成熟开源组件，并通过 Holo 的 ToolRegistry / journal / verifier / benchmark harness 包装。
- 已有本地自研能力保留为 fallback、审计层和兼容层，不再作为长期主线反复扩写。

## 2. 采用成熟组件，但不让它们接管 Holo

Kernel v3 不能变成 LangGraph、AutoGen、OpenBB、Docling 或 EdgarTools 的薄 wrapper。正确关系是：

| 层级 | 使用成熟组件 | Holo 保留责任 |
| --- | --- | --- |
| Agent runtime | LangGraph 负责 state graph、checkpoint、resume、interrupt、streaming、subgraph | Holo 定义双层 loop、状态契约、权限、journal、停止条件、benchmark 边界 |
| Multi-agent research | AutoGen 可作为后续多 agent 协作实验框架 | Holo 决定何时需要多 agent、如何合并证据、如何审计每个 agent 的作用 |
| SEC/EDGAR/XBRL | EdgarTools 负责 filing、company facts、XBRL、标准财表和 SEC primitives | Holo 负责证据 provenance、FactLedger、slot binding 提示、gold 隔离 |
| 文档/表格解析 | Docling 负责 PDF/HTML/XLSX/XBRL 等格式转换、表格结构、chunking/API/MCP | Holo 负责任务相关 evidence reduction、citation、claim/fact ledger |
| 金融数据接口 | OpenBB 负责公开/授权金融数据 connector、Python/API/MCP 接口 | Holo 负责问题驱动的数据选择、单位口径检查、calculator/verifier |
| 计算与验证 | 可吸收现有数值/表格库 | Holo 继续记录 FormulaTrace、NumericVerification 和最终 gate |

底层组件可以被替换，Holo 的核心边界不能被替换：

- 模型提出计划、工具调用、slot binding、公式意图和最终答案。
- Host 校验 schema、权限、预算、执行工具、记录 journal、生成 trace、做 post-run scoring。
- Gold/reference 不进入 runtime prompt、tool context、retrieval context 或 memory。
- 禁止答案表、关键词拦截、固定阈值捷径和 host 代替模型做金融结论。

## 3. 初始组件选择

### 3.1 LangGraph：双层 agent loop 的主 runtime 候选

官方文档把 LangGraph 定位为 low-level orchestration framework/runtime，用于 long-running、stateful agents，并强调 durable execution、streaming、human-in-the-loop、persistence、memory 和 fault tolerance。

Kernel v3 应优先用它承载两层 loop：

```text
Outer Finance Research Supervisor
  - 任务理解、预算、阶段控制、是否需要重新检索/重算/反证
  - 管理 evidence ledger / claim ledger / formula traces / failure memory

Inner Finance Solver Loop
  - 针对单个 FinanceBench/FAB/真实金融问题
  - 调用 SEC、文档解析、金融数据、calculator、verifier
  - 产出可评分 final answer 或明确 failure report
```

LangGraph 负责可恢复的执行图；Holo 负责图状态的语义字段、工具边界、journal、评测隔离和 domain verifier。

### 3.2 EdgarTools：SEC/EDGAR/XBRL 主入口

EdgarTools 已提供 Python SEC EDGAR filing 访问、XBRL financial facts、10-K/10-Q/8-K 等 typed objects、company facts、标准财表、文本/section 抽取、DataFrame 输出、缓存和 MCP/AI 集成。Kernel v3 不应继续从零维护所有 SEC filing primitive。

Holo 应把它包装成只读工具：

```text
sec.company.lookup
sec.filing.search
sec.filing.load
sec.xbrl.facts
sec.statement.extract
sec.section.extract
```

工具返回候选事实和 provenance，不返回最终答案。LLM 仍要判断 line item、period、unit、sign convention 和业务解释。

### 3.3 Docling：文档和表格解析层

Docling 覆盖 PDF、HTML、XLSX、XBRL、表格导出、chunking、MCP/API server 和常见 RAG 集成。FinanceBench 的失败模式经常不是“模型不会算”，而是模型没有看到稳定、结构化、可引用的表格行。

Holo 应把 Docling 放在 document parser 层：

```text
document.convert
document.tables.extract
document.chunk
document.grounding.inspect
```

它解决格式和表格结构问题；Holo 仍负责 EvidenceSpec 驱动的 evidence reduction 和 citation discipline。

### 3.4 OpenBB：通用金融数据 connector

OpenBB 的 ODP 是开源金融数据工具集，覆盖 Python、REST API、MCP、AI agents 和研究 dashboard 场景。对于非 SEC filing 的市场数据、宏观数据、价格序列、fundamental connector，继续自研所有接口没有必要。

Holo 应把 OpenBB 放在外部数据层：

```text
market.price.history
market.reference.lookup
fundamental.metric.fetch
macro.series.fetch
```

FinanceBench 主要依赖 filing evidence，但真实金融研究任务需要 SEC、市场、宏观和公司参考数据协同。OpenBB 可作为这部分的成熟 connector 基座。

### 3.5 AutoGen：后续多 agent 协作实验，不作为第一步替代 core loop

AutoGen 官方文档把 AgentChat 用于 conversational single/multi-agent apps，把 Core 用于 event-driven scalable multi-agent AI systems，并明确适合 multi-agent collaboration research。

Kernel v3 当前更紧急的是把工具链和双层 solver loop 做稳。AutoGen 可作为后续研究分支，用于：

- 多 agent 反证/审计角色；
- 专家 agent 协作；
- 分布式 agent runtime 实验；
- 与 Holo journal 对齐的多 agent trace 对比。

它不应先于 LangGraph 双层 loop 和 finance toolchain 落地。

## 4. 下一阶段工程路线

### Phase A：工具链封装优先

先做 `finance_toolchain` 适配层，而不是继续把工具逻辑散落在 runtime 中。

目标接口：

```text
FinanceDataToolchain
  sec: EdgarTools-backed SEC/EDGAR/XBRL tools
  document: Docling-backed parser/table/chunk tools
  market: OpenBB-backed market/fundamental tools
  compute: existing calculator + numeric verifier
  evidence: FactLedger / ClaimLedger / provenance reducer
```

所有工具通过 Holo `ToolRegistry` 暴露，保留 schema、policy、artifact、journal 和 benchmark 隔离。

### Phase B：双层 loop

在工具链稳定后落成：

```text
OuterSupervisorGraph
  -> classify task
  -> choose tool budget
  -> launch / resume inner solver
  -> inspect verifier/failure memory
  -> decide continue, repair, or final gate

InnerFinanceSolverGraph
  -> compile TaskSpec/EvidenceSpec/TransformSpec
  -> retrieve/parse/bind evidence
  -> run calculator/verifier
  -> synthesize answer
  -> return trace-rich result
```

这一步的重点不是多 agent 名词，而是让 agent loop 可恢复、可观察、可中断、可复盘。

### Phase C：live debug50，再 freeze，再 test100

能力报告仍按永久规则执行：

- `debug50` 用来调试系统。
- `test100` 是 held-out 测试。
- fake/offline/schema/unit tests 只能作为工程回归，不得作为金融做题能力。
- 每次 live run 必须保证 gold/reference 只在完成后用于 scoring。

## 5. 这次转向的判断标准

本次迭代成功不看“又加了多少规则”，而看：

- 是否减少自研 SEC/表格/文档 primitive 的维护面；
- 是否让工具返回更稳定、结构化、可引用的事实候选；
- 是否让 LLM 更好地完成 slot binding、公式选择和业务解释；
- 是否让失败能进入 durable memory / failure ledger，下一题可复用；
- 是否提升 live `debug50` 和 held-out `test100` 的真实准确率；
- 是否降低 token 浪费、重复检索和不可恢复长跑失败；
- 是否保持 Holo 的 host-owned 安全边界和审计能力。

## 6. 2026-06-17 第一实现检查点

本记录之后的第一步代码落地是 `kernel_v3/finance/open_components.py`：

```text
finance.toolchain.describe
sec.edgar.company_filings
sec.edgar.financials
document.docling.convert
market.openbb.fetch
```

设计边界：

- 这些工具通过 Holo `ToolRegistry` 注册，进入同一套 manifest、policy、observation、artifact 和 journal 管线。
- `finance.toolchain.describe` 是 read-only，用来告诉模型 EdgarTools、Docling、OpenBB、LangGraph 是否已安装。
- SEC、Docling、OpenBB 工具标记为 `network`，要求 `network:fetch` 权限；没有 live/network budget 的 finance recipe 不开放这些联网工具。
- OpenBB 第一版只允许有限 route allowlist，避免把任意组件调用暴露给模型。
- Docling 第一版只接受 `http(s)` source；本地文件仍走 workspace tools，避免绕过 workspace policy。
- EdgarTools 需要 `EDGAR_IDENTITY` / `SEC_EDGAR_IDENTITY` / `HOLO_SEC_IDENTITY` 环境变量；缺少时工具返回明确诊断，不伪造 SEC 数据。
- 缺少可选依赖时，工具返回 `dependency_missing`，不让 host fallback 推断答案。

这一步不是 live benchmark 分数。它是成熟组件工具链的工程接入点，为后续真实 live `debug50` 调试和双层 LangGraph loop 做准备。

工程回归：

```bash
.venv/bin/python -m py_compile kernel_v3/finance/open_components.py kernel_v3/finance/__init__.py kernel_v3/agent/runtime.py kernel_v3/finance/task_compiler.py kernel_v3/capabilities.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_open_components.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py::test_calculator_rejects_unsafe_expressions tests/test_kernel_v3_finance_engine.py::test_finance_numeric_verifier_is_registered_as_read_only_tool -q
```

最新结果：新增成熟组件工具边界测试 `8 passed`，旧 calculator/verifier 注册回归 `2 passed`，py_compile 通过。

## 7. 2026-06-17 EdgarTools 实际接通检查点

第一批真正安装并 live smoke 的成熟组件是 EdgarTools：

```text
requirements-finance-open-components.txt
  edgartools==5.36.0
```

本次修正了三个接入稳定性问题：

- EdgarTools import 默认会尝试写 `~/.edgar`；Holo 适配层现在在 import 前把 `EDGAR_LOCAL_DATA_DIR` 和 `EDGAR_CACHE_DIR` 默认指向 `/tmp/holo-edgar-cache/...`，并保留用户显式环境变量优先级。这避免污染 WSL home 和 `.state`。
- 新版 EdgarTools 的 `filing_obj.financials` 可能是 property 而非 callable；`sec.edgar.financials` 现在同时兼容 property 和 method API。
- Pandas/DataFrame 输出中的非有限浮点如 `NaN` 会被 sanitizer 转成 `None`，保证 Holo observation / journal 是严格 JSON。

Live smoke 结果，不是 benchmark 分数：

```text
tool: sec.edgar.company_filings
input: identifier=MMM, form=10-K, limit=1
status: ok
record_count: 1
example: accession_number=0000066740-26-000014, form=10-K, filing_date=2026-02-03, reportDate=2025-12-31

tool: sec.edgar.financials
input: identifier=MMM, form=10-K, statement=cash_flow_statement, limit=5
status: ok
record_count: 5
strict_json_check: json.dumps(observation, allow_nan=False) passed
```

这说明 Holo 的 SEC 成熟组件路径已经从 `dependency_missing` 进入可执行状态：模型可以在 planner 中选择 EdgarTools-backed filing discovery 或 SEC/XBRL financial statement candidates；host 仍只返回候选 facts/records，最终 metric、period、line item、unit、formula 和解释仍由 LLM 决定。

## 8. 来源

- LangGraph overview: <https://docs.langchain.com/oss/python/langgraph/overview>
- AutoGen documentation: <https://microsoft.github.io/autogen/stable/>
- EdgarTools repository: <https://github.com/dgunning/edgartools>
- Docling documentation: <https://docling-project.github.io/docling/>
- OpenBB repository: <https://github.com/OpenBB-finance/OpenBB>
