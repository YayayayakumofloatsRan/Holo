# Kernel v3 FB/FQA Tool Coverage Audit

Date: 2026-06-18

本文件记录开跑 live debug50 前对 FinanceBench / FQA(FinQA) 题型、工具链和缺口的重新审查。

## 结论

当前 `finance-capability` 的工具面已经覆盖 FinanceBench 与 FinQA/FQA 的主要题型闭包：

```text
task compile
  -> source/context acquisition
  -> document/context/table parsing
  -> evidence/fact/slot ledger
  -> table SQL or calculator transform
  -> numeric verifier
  -> semantic synthesis / replan
```

本次发现的真实缺口不是 SEC、calculator 或 verifier，而是 FinQA/FQA 的
`provided context -> structured rows/tables -> data.table.query` 入口不够直接。
已新增 `provided_context.parse`，用成熟 Python 数据组件承接 context-to-table：

- `pandas` / `read_html`：HTML table to DataFrame。
- `lxml` / `bs4`：pandas HTML table parser backend。
- Holo parser glue：只做结构化，不做语义判断，不选择答案。

`provided_context.parse` 输出 `text_blocks`、`tables`、`data_table_payloads` 和 artifact，
模型可以 one-shot 将结果交给 `data.table.query`、`finance.slot_bind`、`calculator.compute`
和 `finance.verify_numeric`。

这不是 live benchmark 成绩；它是开跑前的工具接口和执行链路证据。

## 题型审计

本地 no-gold requirements audit 使用 question text 与 public metadata，不读取 gold/reference。

### FinanceBench debug50

- item_count: 50
- contract_coverage_rate: 1.0
- source_acquisition: 50/50
- structured_sec_facts: 47/50
- document_table_extraction: 50/50
- table_operations: 22/50
- arithmetic: 44/50
- numeric_verification: 42/50
- temporary_workbench: 22/50

### FinanceBench test100

- item_count: 100
- contract_coverage_rate: 1.0
- source_acquisition: 100/100
- structured_sec_facts: 99/100
- document_table_extraction: 100/100
- table_operations: 46/100
- arithmetic: 76/100
- numeric_verification: 73/100
- temporary_workbench: 46/100

### FinQA/FQA oracle100

- item_count: 100
- prompt_context: 100/100
- reference_program_available: 100/100, scoring-only
- table_hint: 100/100
- arithmetic: 81/100
- numeric_verification: 81/100
- table_operations: 20/100
- temporary_workbench: 20/100

FinQA/FQA 与 FinanceBench 的不同点：FinQA 主要难点不是 live source acquisition，
而是题目给定 report context 的表格结构化、多步 transform 和公式 trace。

## 题型到工具矩阵

| 题型 | 核心能力 | 模型可调用工具 |
| --- | --- | --- |
| Filing line item / disclosure | 找官方 filing、提取目标 line item、引用来源 | `retrieval.run`, `sec.edgar.company_filings`, `sec.edgar.financials`, `document.docling.convert`, `document.trafilatura.extract`, `artifact.read`, `artifact.query` |
| Filing table extraction | PDF/HTML/table 转结构化候选，后续查询 | `document.docling.convert`, `document.trafilatura.extract`, `provided_context.parse`, `data.table.query`, `script.exec` |
| Defined formula calculation | 绑定事实、执行公式、保留 FormulaTrace | `finance.slot_bind`, `calculator.compute`, `math.sympy.compute`, `data.table.query` |
| Business judgment after calculation | 结合比例和业务语境判断，不能用硬阈值 | LLM semantic synthesis + `finance.verify_numeric` |
| Driver / bridge / reconciliation | 抽取 management discussion 或 bridge table，计算/排序/解释 driver | `document.docling.convert`, `provided_context.parse`, `data.table.query`, `calculator.compute`, `script.exec` |
| Table ranking / comparison | 行列过滤、排序、聚合、极值比较 | `provided_context.parse`, `data.table.query`, `calculator.compute` |
| Multi-period / multi-entity | 多公司、多期间事实绑定和比较 | `sec.edgar.financials`, `provided_context.parse`, `finance.slot_bind`, `data.table.query`, `calculator.compute` |
| Market / macro context | 价格、宏观、非 filing 数据 | `market.openbb.fetch`, `retrieval.run` |
| FinQA/FQA provided report context | prompt context 中 text/table 结构化，不读取 reference program | `provided_context.parse`, `data.table.query`, `calculator.compute`, `finance.verify_numeric` |

## 新增工具合同

`provided_context.parse`

```json
{
  "context": "raw provided context string",
  "context_format": "auto|finqa|html|markdown|json",
  "table_name_prefix": "optional safe table prefix",
  "max_rows": 500,
  "max_chars": 12000
}
```

返回：

- `text_blocks`: `pre_text` / `post_text` / free text blocks。
- `tables`: query-ready rows with safe column names。
- `data_table_payloads`: 可直接转交 `data.table.query` 的 payload skeleton。
- `artifact_id` / `artifact.read_hint`: 长结果可回读。

Host boundary:

- host 只解析结构、限制大小、记录 artifact。
- LLM 选择相关行列、公式、单位、业务解释和是否继续取证。
- reference program / gold answer 不进入 prompt。

## 当前门禁结果

验证命令：

```bash
.venv/bin/python -m py_compile kernel_v3/finance/open_components.py kernel_v3/finance/tool_catalog.py kernel_v3/finance/tool_readiness.py kernel_v3/finance/__init__.py kernel_v3/agent/runtime.py kernel_v3/deep_loop.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py -q
.venv/bin/python -m kernel_v3.cli bench finance-tool-audit --execute-local-smoke --format json
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py tests/test_kernel_v3_execution_profile.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
```

结果：

- focused open/readiness tests: `32 passed`
- finance-tool-audit smoke: `status=ok`, `local_smoke_status=ok`, `allowed_tools_count=22`
- structural loop/profile tests: `92 passed`
- finance engine tests: `311 passed`

## 剩余边界

- Docling/OpenBB 仍保持隔离 worker，不进入主 UbuntuHolo venv。
- `openpyxl`、`pdfplumber`、`camelot`、`tabula` 当前未作为 FB/FQA 必备项安装；若 live 题型证明需要本地 Excel/PDF table fallback，再作为 isolated document worker 扩展，而不是污染主环境。
- 以上结果不是 FinanceBench/FQA live 分数。能力分数仍必须来自 live model run，gold/reference 只用于 post-run scoring。

## 外部组件来源

- pandas `read_html`: https://pandas.pydata.org/docs/reference/api/pandas.read_html.html
- lxml HTML parser: https://lxml.de/lxmlhtml.html
- Beautiful Soup documentation: https://beautiful-soup-4.readthedocs.io/en/latest/
