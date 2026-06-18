# Kernel v3 Finance Toolchain Readiness

Date: 2026-06-17

This document records the FB/FQA tool exposure and open-component readiness boundary for Kernel v3.

## 结论

`bench finance-tool-audit` 是金融做题前的系统 preflight。它检查工具入口、模型可见性、host policy、provider prompt 压缩、成熟开源组件、临时工作台能力，以及 tool discovery / artifact 回读 / slot binding / numeric verifier 的本地执行链路。

它不是 FinanceBench 或 FinQA 成绩声明，不读取 benchmark gold/reference，不进行离线假测评。

## 命令

```bash
.venv/bin/python -m kernel_v3.cli bench finance-tool-audit --format text
```

可选执行本地 no-internet smoke：

```bash
.venv/bin/python -m kernel_v3.cli bench finance-tool-audit --execute-local-smoke --format text
```

查看并生成隔离 worker 配置草案：

```bash
.venv/bin/python -m kernel_v3.cli bench finance-tool-workers --format text
.venv/bin/python -m kernel_v3.cli bench finance-tool-workers --write-setup --format text
```

这些命令是工具入口和组件状态检查，不是长回归，也不是金融做题成绩。

## 2026-06-18 门禁收紧

开跑 live debug50 前，readiness 门禁不再只检查“工具是否注册”。它还必须确认模型 one-shot 自组装工作台所需的闭环：

- `tool.discovery` 在 provider compact payload 和 planner prompt 中可见，并可返回指定工具 schema。
- `artifact.read` / `artifact.query` 在模型可见面和 host policy 中可用，并能读取本地 `ArtifactStore` fixture。
- `finance.slot_bind` 能校验模型选择的 `FinanceFact` 和 formula request，返回 calculator-ready payload。
- `finance.verify_numeric` 能对模型答案和可见事实执行 verifier，返回 observation。
- 本地 smoke 还继续执行 calculator、DuckDB table query、SymPy、Trafilatura 和 `script.exec`。

本次验证命令：

```bash
.venv/bin/python -m py_compile kernel_v3/finance/tool_readiness.py tests/test_kernel_v3_finance_tool_readiness.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_tool_readiness.py -q
.venv/bin/python -m kernel_v3.cli bench finance-tool-audit --execute-local-smoke --format json
.venv/bin/python -m pytest tests/test_kernel_v3_deep_agent_loop.py tests/test_kernel_v3_finance_open_components.py tests/test_kernel_v3_finance_tool_readiness.py tests/test_kernel_v3_execution_profile.py -q
```

2026-06-18 后续题型覆盖审查见
`docs/KERNEL_V3_FB_FQA_TOOL_COVERAGE_2026-06-18_ZH.md`。该审查确认
FinQA/FQA 的 P0 缺口是 provided report context 到 query-ready table 的稳定 ABI，
并新增 `provided_context.parse`：

- 输入 FinQA 风格 `pre_text/table/post_text`、HTML table、Markdown pipe table 或 JSON context。
- 输出 `text_blocks`、`tables`、`data_table_payloads` 和 artifact。
- 使用成熟组件 `pandas` / `lxml` / `beautifulsoup4` 做结构化解析。
- Host 只做结构化，不做语义选择；LLM 仍决定行列、公式和答案。

更新后结果：focused open/readiness tests `32 passed`，本地 finance-tool-audit smoke
`status=ok` / `local_smoke_status=ok` / `allowed_tools_count=22`，结构回归 `92 passed`，
finance-engine tests `311 passed`。这仍然只是工具接口和执行链路证据，不是 FinanceBench/FQA 分数。

## 覆盖的 FB/FQA 工具类别

- FinanceBench filing retrieval: `tool.discovery`, `retrieval.run`, `sec.edgar.company_filings`, `sec.edgar.financials`, `artifact.read`, `artifact.query`, `provided_context.parse`, `document.trafilatura.extract`, `document.docling.convert`
- FinanceBench filing table extraction: `artifact.read`, `artifact.query`, `document.trafilatura.extract`, `document.docling.convert`, `data.table.query`, `workspace.write`, `shell.exec`, `script.exec`
- FinanceBench numeric ratio reasoning: `finance.slot_bind`, `calculator.compute`, `finance.verify_numeric`, `data.table.query`, `math.sympy.compute`
- FinanceBench market or macro context: `retrieval.run`, `market.openbb.fetch`, `calculator.compute`, `finance.verify_numeric`
- FinQA/FQA report context numeric reasoning: `tool.discovery`, `provided_context.parse`, `calculator.compute`, `finance.slot_bind`, `finance.verify_numeric`, `data.table.query`, `math.sympy.compute`
- FinQA/FQA table/program-like transforms: `provided_context.parse`, `data.table.query`, `finance.slot_bind`, `calculator.compute`, `math.sympy.compute`, `finance.verify_numeric`
- Temporary workbench assembly: `tool.discovery`, `finance.toolchain.describe`, `artifact.read`, `artifact.query`, `provided_context.parse`, `workspace.list`, `workspace.search`, `file.read`, `workspace.write`, `shell.exec`, `script.exec`
- Long-result artifact boundary: SEC/EDGAR, document extraction/conversion, OpenBB, and DuckDB table-query tools return bounded observations plus `artifact_id` / `artifact.read` hints while storing the full JSON tool payload in `ArtifactStore`.
- Document evidence visibility: `document.docling.convert` now gives PDF URLs a lightweight PDF-reader path before heavy Docling, reports isolated worker failures as observations, and returns `focus_snippets` before truncated text. The snippets are only candidate evidence windows selected from model-provided/default finance terms; the LLM still chooses facts, line items, formulas, and conclusions.
- Open-component evidence adapter: finance tool observations from Docling, Trafilatura, SEC EdgarTools, OpenBB, DuckDB, and SymPy can now enter the same synthetic `toolchain_grounding` evidence/citation path as workspace/script tools. This prevents successful model-called document tools from being discarded merely because no separate `retrieval.run` record exists.
- Live proof point: `.state/kernel_v3/bench/finance/fb_debug50_stream_grounding_o000_l001_20260617.jsonl` passed one live FinanceBench debug row (`financebench_id_03029`) with Docling/SEC tool observations, synthetic toolchain grounding, finance fact/claim ledgers, formula trace, numeric verifier, verifier gate, and synthesis gate. This is a single-row debug result only.

## 隔离组件策略

主 Holo venv 保持轻量稳定。重组件不直接装入主 venv，而是通过 JSON subprocess worker 调用。

当前本机默认 worker 路径：

- Document worker: `.holo_components/docling-worker/bin/python`
- Market worker: `.holo_components/openbb-worker/bin/python`
- OpenBB home: `.holo_components/openbb-home`

Holo 会优先读取显式环境变量；如果没有设置环境变量，会自动发现以上 repo-local worker。`.holo_components/` 被 git 忽略，不进入提交。

Document worker:

```bash
python -m venv /path/to/holo-doc-worker
/path/to/holo-doc-worker/bin/python -m pip install -r requirements-finance-isolated-documents.txt
export HOLO_DOCLING_PYTHON=/path/to/holo-doc-worker/bin/python
```

Market worker:

```bash
python -m venv /path/to/holo-market-worker
/path/to/holo-market-worker/bin/python -m pip install -r requirements-finance-isolated-market.txt
export HOLO_OPENBB_PYTHON=/path/to/holo-market-worker/bin/python
```

Generic fallback:

```bash
export HOLO_FINANCE_COMPONENT_PYTHON=/path/to/shared-finance-worker/bin/python
```

OpenBB 默认会使用 `Path.home()` 写配置。Kernel v3 worker subprocess 会把 OpenBB 的 `HOME` 重定向到 repo-local `.holo_components/openbb-home`；也可显式设置：

```bash
export HOLO_OPENBB_HOME=/path/to/openbb-home
```

Timeout:

```bash
export HOLO_FINANCE_COMPONENT_TIMEOUT_SECONDS=120
```

`requirements-finance-isolated-documents.txt` 默认只安装 score-critical 的 Docling document/table conversion 路径。`playwright`/`crawl4ai` 属于后续动态页面/浏览器抓取扩展，不能阻塞 FB/FQA filing 解析主路径；需要时单独安装。

Live finance runs should invoke `.venv/bin/python -m kernel_v3.cli ...` rather
than system `python3`: the project venv contains EdgarTools, Trafilatura, DuckDB,
PDF readers, and related score-critical packages. Using system Python can make
the agent loop look broken even when the repo-local toolchain is installed.

## 安全边界

- LLM 决定是否调用工具、调用哪个工具、payload 怎么填、证据是否足够、公式如何选择。
- Host 只做 schema、policy、budget、journal、artifact、citation、numeric verifier 和 gold isolation。
- 长 SEC/table/document/market payload 默认进入 artifact blob；下一轮模型上下文只拿短摘要和可审计读取入口。
- Docling/OpenBB worker 失败会作为 observation 返回，agent loop 应重新规划，host 不会伪造答案。
- `finance-tool-audit` 输出中的 `capability_claim=false` 和 `benchmark_progress_claim=false` 是硬边界。

## 默认验证纪律

以后工具链和 agent-loop 修改默认只做窄检查：

- 与改动直接相关的定点 unit tests。
- `finance-tool-audit --execute-local-smoke`，用于确认模型可见工具、host policy、schema、临时工作台和本地 no-internet 工具链。
- `finance-tool-workers`，用于确认 Docling/OpenBB 是否通过隔离 worker 可用。

长回归不作为默认动作。FinanceBench/FAB/FinQA 能力进展只允许来自明确启动的 live model/live retrieval 运行，并且 gold/reference 只能在题目完成后评分使用。
