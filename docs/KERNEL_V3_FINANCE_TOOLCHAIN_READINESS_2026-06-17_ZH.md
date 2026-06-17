# Kernel v3 Finance Toolchain Readiness

Date: 2026-06-17

This document records the FB/FQA tool exposure and open-component readiness boundary for Kernel v3.

## 结论

`bench finance-tool-audit` 是金融做题前的系统 preflight。它检查工具入口、模型可见性、host policy、provider prompt 压缩、成熟开源组件和临时工作台能力。

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

## 覆盖的 FB/FQA 工具类别

- FinanceBench filing retrieval: `retrieval.run`, `sec.edgar.company_filings`, `sec.edgar.financials`, `document.trafilatura.extract`, `document.docling.convert`
- FinanceBench filing table extraction: `document.trafilatura.extract`, `document.docling.convert`, `data.table.query`, `workspace.write`, `shell.exec`, `script.exec`
- FinanceBench numeric ratio reasoning: `calculator.compute`, `finance.verify_numeric`, `data.table.query`, `math.sympy.compute`
- FinanceBench market or macro context: `retrieval.run`, `market.openbb.fetch`, `calculator.compute`, `finance.verify_numeric`
- FinQA/FQA report context numeric reasoning: `calculator.compute`, `finance.verify_numeric`, `data.table.query`, `math.sympy.compute`
- FinQA/FQA table/program-like transforms: `data.table.query`, `calculator.compute`, `math.sympy.compute`, `finance.verify_numeric`
- Temporary workbench assembly: `workspace.list`, `workspace.search`, `file.read`, `workspace.write`, `shell.exec`, `script.exec`
- Long-result artifact boundary: SEC/EDGAR, document extraction/conversion, OpenBB, and DuckDB table-query tools return bounded observations plus `artifact_id` / `artifact.read` hints while storing the full JSON tool payload in `ArtifactStore`.
- Document evidence visibility: `document.docling.convert` now gives PDF URLs a lightweight PDF-reader path before heavy Docling, reports isolated worker failures as observations, and returns `focus_snippets` before truncated text. The snippets are only candidate evidence windows selected from model-provided/default finance terms; the LLM still chooses facts, line items, formulas, and conclusions.

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
