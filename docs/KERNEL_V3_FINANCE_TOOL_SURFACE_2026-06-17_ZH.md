# Kernel v3 2026-06-17 Finance Tool Surface

记录时间：2026-06-17 CST +0800
分支：`kernel-v3`
状态：完整工具目录已落地，轻量核心开源组件已安装，重组件进入隔离安装边界。

## 1. 目标

本次迭代不是继续按单题补规则，而是把金融 Agent 做题所需的工具面板一次性列清楚，并让 LLM 能 one-shot 地调用：

```json
{
  "kind": "tool",
  "name": "one registered tool name",
  "payload": "object matching the selected tool schema",
  "reasons": "why this tool is needed now",
  "side_effect_class": "read|network|shell|write"
}
```

Holo 可以暴露工具、校验 schema、执行、记录、验证和停止；LLM 仍负责判断什么时候调用什么、怎么调用、证据是否足够、公式如何组织、最终答案如何解释。

## 2. 完整工具族

`kernel_v3/finance/tool_catalog.py` 现在定义 15 个金融做题工具族：

1. `agent_loop_orchestration`：persistent loop、replan、termination、handoff。成熟组件候选：LangGraph / AutoGen / CrewAI；当前 LangGraph 已作为 finance/web/long profile 的 active loop backend，Holo 保留 host 边界。
2. `llm_provider_gateway`：模型调用、fallback、usage、provider normalization。成熟组件候选：LiteLLM。
3. `structured_output_schema`：JSON action、schema validate、typed packets、repair。成熟组件：Pydantic。
4. `search_discovery`：搜索 official filing、issuer IR、source document、market/macro/news candidate。候选：SearXNG；当前由 `retrieval.run` 和 Holo source providers 承担。
5. `network_fetch_crawl_browser`：bounded fetch、page extraction、dynamic page/browser。候选：Trafilatura / Crawl4AI / Playwright；当前轻量安装 Trafilatura。
6. `sec_edgar_xbrl`：SEC submissions、companyfacts、XBRL、filings、accessions、statement candidates。成熟组件：EdgarTools，已接入 `sec.edgar.company_filings` 和 `sec.edgar.financials`。
7. `document_table_conversion`：PDF/HTML/XLSX/XBRL/CSV、table preservation、chunking。成熟组件：Docling / Pandas；Docling wrapper 已接入，但 full package 需隔离安装。
8. `market_macro_fundamental_data`：price、fundamental、macro、crypto、currency、index、FRED-style data。成熟组件：OpenBB；wrapper 已接入，但 full OpenBB 放入隔离安装边界。
9. `calculator_math_stats`：DIO、CAGR、margin、bps、multiple、DCF/LBO arithmetic。当前 `calculator.compute` 使用 Python Decimal；SymPy 已安装用于未来复杂数学。
10. `table_dataframe_query`：table normalization、joins、SQL、large evidence table analysis。Pandas 已有，Polars/DuckDB 已安装。
11. `workspace_code_execution`：local file/search/read/write、temporary parser、script/shell execution。Holo-owned，配合 Python/Pytest。
12. `evidence_provenance_verification`：FactLedger、ClaimLedger、FormulaTrace、target binding、numeric verifier、synthesis gate。Holo-owned，不外包。
13. `memory_cache_storage`：durable memory、ArtifactStore、JournalStore、run cache。SQLite 当前使用，DuckDB 可用于 trace analytics。
14. `process_observability_visualization`：live process visibility、PID/RSS、stage、tool calls、metrics。Rich 已用于 `bench finance-progress --format rich`；OpenTelemetry 已安装。
15. `benchmark_evaluation`：FinanceBench/FAB/FinQA style runs、dev/test split、post-run scoring、engineering regression。Holo-owned，Pytest 只用于工程回归，不能作为 finance live 能力证据。

## 3. 已安装的轻量核心

`requirements-finance-open-components.txt` 现在 pin 住核心工具链：

```text
edgartools==5.36.0
pandas==3.0.3
pydantic==2.13.4
rich==15.0.0
langgraph==1.2.5
langchain-core==1.4.7
litellm==1.89.1
trafilatura==2.1.0
polars==1.41.2
duckdb==1.5.3
sympy==1.14.0
opentelemetry-api==1.42.1
opentelemetry-sdk==1.42.1
```

安装后 smoke：

```text
installed: edgar, langgraph, langchain-core, litellm, trafilatura, polars,
           duckdb, sympy, opentelemetry, rich, pandas, pydantic
missing:   docling, openbb
```

`finance_toolchain_install_summary()` 当前统计：

```text
installed_count: 16
missing_count: 9
installed: duckdb, edgartools, langgraph, litellm, opentelemetry, pandas,
           polars, pydantic, pytest, python, python_decimal,
           python_statistics, rich, sqlite3, sympy, trafilatura
missing: autogen, crawl4ai, crewai, docling, langfuse, openbb, phoenix,
         playwright, promptfoo
```

## 4. 重组件隔离边界

第一次尝试直接安装 full `docling==2.102.2` 时，pip 解析链开始拉 `torch`、`torchvision`、CUDA 13 系列包。这个路径会显著增加主 venv 体积和 UbuntuHolo 不稳定风险，因此已中断，并把 Docling/OpenBB 放入隔离安装边界：

```text
# docling==2.102.2
# openbb==4.7.2
# playwright
# crawl4ai
# langfuse
# arize-phoenix
```

这不是放弃成熟组件，而是避免把重型 parser/browser/market connector 直接塞进主 harness。正确路线是：

- wrapper 和 tool schema 已在主系统中可见；
- 缺依赖时工具返回 `dependency_missing`，不会伪造结果；
- 后续用隔离 venv、容器或受限 worker 安装 Docling/OpenBB；
- Holo 主 loop 通过 host policy 调用隔离 worker，继续保留 journal、redaction、budget、gold isolation。

## 5. 模型 one-shot 调用协议

`finance.toolchain.describe` 现在返回：

- `tool_surface_schema`
- `one_shot_tool_protocol`
- `agent_loop_contract`
- `tool_surface`
- `install_summary`
- legacy `components`
- `tool_names`
- `network_tool_names`

Planner 首包也会携带 compact `toolchain_install_summary`，让模型在
one-shot 选择工具前知道哪些成熟组件已经可用、哪些重组件处于隔离/缺失状态。
这只是可用性提示，不是 host 替模型选择数据路径。

同日 agent loop 审查已把 provider prompt compact 路径一并收紧：真实发给
模型的 `agent_runtime_directive.tool_selection` 非轻量路径保留 24 项，并携带
`tool_selection_count`、`toolchain_install_summary`、`finance_agent_loop_contract`
和 compact `llm_first_finance_template.standard_tool_interface`。这保证模型看到
的是完整 one-shot 工具接口和通用做题 loop，而不是只看到 runtime 内部的工具目录。

`finance_agent_loop_contract` 是 benchmark-agnostic 的：它只描述
`task_compile -> evidence_acquire -> ledger_bind -> transform_compute ->
semantic_synthesis -> verify_or_replan` 六阶段通用工作台，以及直接抽取、公式
计算、计算后业务判断、driver/bridge、table ranking/comparison 等任务族。它不包含
debug50 行号、FinanceBench id、gold/reference 或答案规则。

Planner directive 已同步更新：当数据路径不确定时，LLM 应先调用 `finance.toolchain.describe`，然后自己选择下一步具体工具，比如：

```json
{
  "kind": "tool",
  "name": "sec.edgar.financials",
  "payload": {
    "identifier": "MMM",
    "form": "10-K",
    "statement": "cash_flow_statement",
    "limit": 80
  },
  "reasons": ["official SEC/XBRL statement candidates are needed"],
  "side_effect_class": "network"
}
```

或者在需要表格归一化时选择：

```json
{
  "kind": "tool",
  "name": "script.exec",
  "payload": {
    "language": "python",
    "expected_output": "json",
    "script": "..."
  },
  "reasons": ["normalize extracted table rows before formula binding"],
  "side_effect_class": "shell"
}
```

这些接口不是规则答案。LLM 仍决定要不要用工具、选哪条证据、公式如何写、何时停止。Host 只执行和验证。

## 6. 本次工程改动

- 新增 `kernel_v3/finance/tool_catalog.py`，作为机器可读完整工具目录。
- `finance.toolchain.describe` 扩展为完整工具面板，而不是仅报告 EdgarTools/Docling/OpenBB/LangGraph 四个组件。
- `finance.toolchain.describe` 和 planner/provider compact 现在暴露 benchmark-agnostic `finance_agent_loop_contract`，让模型首轮即可按通用工作台 loop 组织任务，而不是把所有工作塞进一次 `retrieval.run`。
- 新增可调用成熟组件 wrapper：`document.trafilatura.extract` 用于 HTML/main text 抽取，`data.table.query` 用 DuckDB/Pandas 对证据表执行只读 SQL，`math.sympy.compute` 用 SymPy 执行模型提出的符号/高精度计算。
- Runtime planner directive 和 finance task compiler 都暴露 `finance.toolchain.describe` 与 one-shot follow-up；finance profile 不再只有 `require_numeric_verifier` 时才看到工具链。
- Runtime planner directive 和 provider prompt compact 都保留完整 finance open tool surface，不再因为前 6 个工具截断而让模型看不到 SEC/Docling/Trafilatura/OpenBB/DuckDB/SymPy 等工具。
- `_RecipeEvaluator` 对可恢复工具链失败返回 `continue` 让 LLM 重规划，例如 `dependency_missing`、`component_call_failed`、`route_not_allowlisted`、`unsupported_source`、`unsafe_or_unsupported_sql`。`policy_block`、预算 guard 和权限边界仍然按 host 安全语义阻断。
- `bench finance-progress --format rich` 使用 Rich 渲染 run-root、process、stage、diagnostics、counters、recent events。
- `requirements-finance-open-components.txt` 改为轻量核心 pin，重组件明确隔离。

## 7. 边界

- 禁止把工具目录变成题目规则表。
- 禁止 host 预计算 benchmark 答案。
- 禁止 fake/offline tests 作为金融能力证据。
- Gold/reference 只允许 post-run scoring，不进入 prompt、tool、retrieval、memory。
- 工具组件越成熟，越应该承担底层 primitive；但判断、证据绑定、公式选择、最终解释必须由 LLM 和 Holo verifier 完成。
- 工具执行失败是 observation，不是 host 语义结论；可恢复失败进入 agent loop 重规划，安全/权限失败保持阻断。

## 8. 参考

- EdgarTools: <https://github.com/dgunning/edgartools>
- LangGraph: <https://docs.langchain.com/oss/python/langgraph/overview>
- LiteLLM: <https://docs.litellm.ai/docs/>
- Docling: <https://docling-project.github.io/docling/>
- OpenBB: <https://docs.openbb.co/platform/>
- DuckDB Python: <https://duckdb.org/docs/stable/clients/python/overview.html>
- SymPy: <https://www.sympy.org/en/index.html>
- Rich: <https://rich.readthedocs.io/en/stable/introduction.html>
- OpenTelemetry: <https://opentelemetry.io/docs/what-is-opentelemetry/>
