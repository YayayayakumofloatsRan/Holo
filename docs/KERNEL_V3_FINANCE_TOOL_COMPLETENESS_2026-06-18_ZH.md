# Kernel v3 Finance Tool Completeness Check

Date: 2026-06-18

本文件记录“开跑 live debug50 前，FB/FQA 所需工具是否齐全”的当前结论。

## 结论

FB/FQA score-critical 工具链已齐全：

- `finance-tool-audit --execute-local-smoke` 返回 `status=ok`。
- `fb_fqa_required_tool_status=ok`。
- `required_missing_components=[]`。
- `allowed_tools_count=23`。
- `provider_tool_selection=23`, `planner_prompt_tool_selection=23`。
- Docling/OpenBB 不装进主 venv，但隔离 worker 已 ready。

这不是 FinanceBench/FQA 做题分数；它只是工具入口、模型可见性、host policy、组件和本地执行链路的 preflight。

## 必备工具面

- Tool discovery/context: `tool.discovery`, `artifact.read`, `artifact.query`
- Retrieval/source: `retrieval.run`, `sec.edgar.company_filings`, `sec.edgar.financials`
- Document/context/table: `document.docling.convert`, `document.trafilatura.extract`, `provided_context.parse`, `data.table.query`
- Numeric/finance transforms: `finance.slot_bind`, `calculator.compute`, `math.sympy.compute`, `calendar.days_between`, `finance.verify_numeric`
- Market/macro: `market.openbb.fetch`
- Temporary workbench: `workspace.list`, `workspace.search`, `file.read`, `workspace.write`, `shell.exec`, `script.exec`
- Tool surface introspection: `finance.toolchain.describe`

## 新补齐项

`calendar.days_between` 用于 DIO/DSO/DPO/CCC 等可能需要实际财年/日历天数的题。它只返回日期差和 year-fraction transform；LLM 仍决定公式口径，不由 host 规则替模型判断。

`finance-tool-audit` 现在输出 `completeness_tiers`：

- `fb_fqa_score_critical_required_tools`: 必备工具完整性门禁。
- `local_execution_smoke`: 本地 no-internet smoke 执行门禁。
- `optional_enhancements`: 浏览器抓取、observability、prompt eval、多 agent 框架等增强项。

## 增强项边界

当前 optional enhancement missing components:

- `autogen`, `crewai`: 多 agent/子 agent 框架；当前明确先做成熟单 agent loop，不阻塞 FB/FQA。
- `crawl4ai`, `playwright`: 动态浏览器抓取；FinanceBench/FinQA 主路径是 SEC/public filing/context/table，不阻塞当前 debug50。
- `langfuse`, `phoenix`: tracing/observability；有助于分析，但不是做题必备工具。
- `promptfoo`: eval CLI；不作为 live score 证据来源。

这些增强项只有在 live 题型证明需要时才进入隔离 worker 或独立工具，不直接污染主 UbuntuHolo venv。

## 验证

```bash
.venv/bin/python -m py_compile kernel_v3/finance/open_components.py kernel_v3/finance/__init__.py kernel_v3/finance/tool_readiness.py kernel_v3/finance/tool_catalog.py kernel_v3/agent/runtime.py kernel_v3/deep_loop.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m kernel_v3.cli bench finance-tool-audit --execute-local-smoke --format json
.venv/bin/python -m kernel_v3.cli bench finance-tool-workers --format json
```

结果：

- open/readiness: `33 passed`
- finance engine: `311 passed`
- finance-tool-audit: `status=ok`, `fb_fqa_required_tool_status=ok`, `local_smoke_status=ok`, `allowed_tools_count=23`, `provider_tool_selection=23`, `planner_prompt_tool_selection=23`
- finance-tool-workers: `status=ok`, `missing_workers=[]`
