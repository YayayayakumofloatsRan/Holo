# Kernel v3 Finance Results Snapshot - 2026-06-16

Purpose: record the finance problem-solving evidence that is already supported
by local benchmark artifacts, and separate it from claims that still need fresh
live reruns.

## Bottom Line

Finance problem-solving remains the core objective. The strongest local evidence
is still the 2026-06-14 live FinAgent/FAB-family run record, not today's code
changes alone.

Current fresh live rerun status on 2026-06-16: blocked by provider account
availability, not by retrieval and not by a solved benchmark result. The earlier
smoke summary
`.state/kernel_v3/bench/finance/run_live_smoke_current_o000_l001_20260616.summary.json`
recorded `processor_error_counts={"missing_api_key_env": 1}`, `tokens=0`,
`retrieval_runs=0`, and `0/1` pass. After the Windows `DEEPSEEK_API_KEY` was
made available to the WSL process, a new live FinanceBench row-0 smoke reached
online retrieval but DeepSeek returned `HTTP 402: Insufficient Balance` before
any model tokens were produced. This is a provider/account blockage, not a
capability score.

Fake/offline tests are permanently disallowed as finance capability evidence.
They may still be used only as labeled code-regression, schema, compile, or
safety checks. Any reported finance benchmark progress must come from an
online/live model run with benchmark gold/reference material kept out of model
context.

## Evidence-Backed Results

| Run | Dataset / Slice | Result | Notes |
| --- | --- | ---: | --- |
| `run_finagent_full40_after_nonitemized_headline_live_20260614` | FinAgent full40 live | `38/40` (`95.0%`) | Avg tokens `242,333.75`, avg retrieval runs `2.75`, citations present `100%`. |
| `run_finagent_full40_after_nonitemized_headline_live_20260614.rescored` | Same full40, rescored | `39/40` (`97.5%`) | Same live outputs, updated scoring. |
| `run_full40_previous_failures_after_nonitemized_headline_live` | Historical full40 failures regression | `12/12` (`100%`) | Shows previously failing items were closed in that live regression. |
| `run_fabv2_dev10_capability_parallel10_judgefix` | Curated FAB v2 dev10 | dev annotation overall `0.8752`, numeric `1.0000` | Not a strict pass/fail benchmark score; all 10 still carry dealbreaker annotations. Avg tokens `511,061.2`. |
| `run_stable4_latest_after_pfe_acquisition_fixes` | Four representative workflow tasks | dev annotation overall `0.9603`, numeric `1.0000` | HD/LOW DIO, KHC adjusted EBITDA bridge, PFE/SGEN transaction multiple, WSC add-back trend style coverage. |
| `run_public27_workflow_v1` | FAB public-style 27 workflow slice | no public gold score | Structural telemetry only: avg tokens `87,928.37`, avg retrieval runs `2.2593`; cannot claim accuracy. |
| `run_fb_debug_o000_l001_htmlcol_fact_20260615_v1` | FinanceBench debug row 0 | `1/1` | 3M FY2022 capital-intensity style row solved with annotation overall `1.0000`. |
| `run_fb_debug_o000_l001_wide_slotbind_20260615_v1` | FinanceBench debug row 0 rerun | `1/1` | Same row, annotation overall `1.0000`; useful smoke, not broad FinanceBench proof. |
| `run_fb_eval_o010_l003_htmlcol_fact_20260615_v1` | FinanceBench offset 10 limit 3 probe | `0/3` | Exposes Adobe-source acquisition/binding failures; annotation overall `0.2929`, numeric `0.0000`. |

## 2026-06-16 Capability Iteration

The `run_fb_eval_o010_l003_htmlcol_fact_20260615_v1` failure cluster was traced
to a generic target-document acquisition issue. Adobe FinanceBench rows use
`https://www.adobe.com/pdf-page.html?pdfTarget=...` wrapper URLs. The old
FinanceBench runtime payload preserved that wrapper as the visible
`source_url`, so the loop could try to fetch the wrapper page and then spend
budget on broad search pages instead of the actual 10-K PDF.

The runtime now reuses the existing retrieval URL utility expansion and emits
the unwrapped PDF URL first in FinanceBench `source_urls` /
`preferred_source_urls`, while keeping the original wrapper URL as provenance.
The same parser now accepts both runtime prompt forms:
`Benchmark target source follows` / `Source URL`, and
`FinanceBench target document metadata follows` / `Document link`.

Static verification on the three failing Adobe rows now maps:

| Offset | Item | First acquisition URL |
| ---: | --- | --- |
| `10` | `financebench_id_04735` | `https://www.adobe.com/content/dam/cc/en/investor-relations/pdfs/ADBE-10K-FY15-FINAL.pdf` |
| `11` | `financebench_id_07507` | `https://www.adobe.com/content/dam/cc/en/investor-relations/pdfs/ADBE-10K-FY16-FINAL.pdf` |
| `12` | `financebench_id_03856` | `https://www.adobe.com/content/dam/cc/en/investor-relations/pdfs/ADBE-10K-FY17-FINAL.pdf` |

This is a source-acquisition capability fix, not a new live accuracy claim.
Fresh live scoring still requires model credentials.

Verification:

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "financebench_doc_retrieval_payload_unwraps_adobe_pdf_target or financebench_doc_retrieval_payload_parses_inline_prompt_labels or financebench_doc_retrieval_payload_stops_inline_period_before_assume_question or financebench_import_modes_keep_gold_out_of_prompt"
.venv/bin/python -m pytest tests/test_kernel_v3_retrieval_document_expansion.py -q -k "adobe_pdf_target_wrapper or direct_url_source_is_fetched_before_profile_discovery_sources or target_document_binding_doc_link_is_fetched_before_search_noise"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_retrieval_document_expansion.py -q
```

Latest result: `102 passed in 273.27s`.

## 2026-06-16 Formula/Slot Follow-Up

After URL unwrapping, the same Adobe FinanceBench failure cluster exposed the
next layer:

- `financebench_id_04735` and `financebench_id_03856` ask for operating cash
  flow ratio, explicitly defined as `cash from operations / total current
  liabilities`. Before this follow-up, the planner returned `not_applicable`.
- `financebench_id_07507` already compiled to `yoy_growth`, but its
  prior/current evidence slots did not carry the income-statement line item.

The finance stack now supports the generic `operating_cash_flow_ratio` formula:

- missing slots: `operating_cash_flow`, `total_current_liabilities`
- expression: `operating_cash_flow / total_current_liabilities`
- evidence specs: cash flow statement for operating cash flow, balance sheet for
  total current liabilities
- SEC concept seeds for known issuers:
  `NetCashProvidedByUsedInOperatingActivities` and `LiabilitiesCurrent`

The `yoy_growth` compiler now binds prior/current operating-income slots to
`income_statement` / `operating income` when the question asks for operating
income growth, and emits an executable transform:
`current_period_value / prior_period_value - 1`, with percent output. Its
missing-fact retrieval payload also seeds known issuers with SEC submissions,
companyfacts, and the relevant companyconcept endpoint such as
`OperatingIncomeLoss` for operating-income growth.

Static verification on the same Adobe rows now shows:

| Offset | Item | Formula | Transform / evidence slots |
| ---: | --- | --- | --- |
| `10` | `financebench_id_04735` | `operating_cash_flow_ratio` | `operating_cash_flow / total_current_liabilities`; `operating_cash_flow` -> cash flow statement; `total_current_liabilities` -> balance sheet |
| `11` | `financebench_id_07507` | `yoy_growth` | `current_period_value / prior_period_value - 1`; prior/current values -> income statement / operating income |
| `12` | `financebench_id_03856` | `operating_cash_flow_ratio` | `operating_cash_flow / total_current_liabilities`; `operating_cash_flow` -> cash flow statement; `total_current_liabilities` -> balance sheet |

Verification:

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "yoy_operating_income or operating_cash_flow_ratio or current_liabilities_metric"
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/finance/task_compiler.py tests/test_kernel_v3_finance_engine.py
git diff --check
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
```

Latest result: targeted slice `6 passed, 243 deselected in 0.28s`; py_compile
and `git diff --check` passed; `249 passed in 2.45s` for finance engine and
`51 passed in 277.47s` for FinanceBench tests.

## 2026-06-16 Direct Evidence Scaffold Follow-Up

The next static FinanceBench scan showed that many rows are not formula-first
questions. They are direct extraction, disclosure, or qualitative comparison
tasks where the fallback compiler previously emitted no `EvidenceSpec`. That
left the later agent loop with a raw prompt but no explicit statement/section
or line-item target.

The compiler now emits generic primary-filing evidence scaffolds for these
non-formula tasks. Examples include capital expenditures, net PP&E, cash and
cash equivalents, current assets/liabilities, dividends, legal proceedings,
registered debt securities, acquisitions, operating geographies, products and
services, customers, segment results, guidance, derivative notionals,
retirement benefit payments, and governance/voting disclosures. These specs do
not contain answers or gold references; they only tell the model-owned loop what
evidence family and slot to acquire.

The same follow-up makes `margin` missing-fact plans more executable. For
example, COGS margin now compiles to `cogs_numerator / revenue_denominator`,
with income-statement evidence targets for both slots.

Static coverage on `financebench_doc_retrieval.jsonl` changed from:

| Slice | Before | After |
| --- | ---: | ---: |
| `debug50` | `14/50` rows with at least one `EvidenceSpec` | `50/50` |
| `test100` | `17/100` rows with at least one `EvidenceSpec` | `100/100` |
| `all150` | `31/150` rows with at least one `EvidenceSpec` | `150/150` |

Verification:

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "direct_metric_evidence or direct_disclosure_evidence or cogs_margin_transform"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q -k "evidence_scaffold or named_splits"
.venv/bin/python -m py_compile kernel_v3/finance/task_compiler.py kernel_v3/finance/formula_planner.py tests/test_kernel_v3_finance_engine.py tests/test_kernel_v3_finance_benchmark.py
git diff --check
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
```

Latest result: targeted finance compiler tests `3 passed, 249 deselected`;
targeted FinanceBench tests `2 passed, 50 deselected`; py_compile and
`git diff --check` passed; full finance engine `252 passed in 4.37s`; full
FinanceBench tests `52 passed in 299.68s`.

## 2026-06-16 Common Formula Planner Follow-Up

After the direct evidence scaffold, the remaining FinanceBench gap was that
many common numeric questions had evidence targets but no executable formula
plan. The planner/compiler/runtime now support these generic formula families:

- `quick_ratio`: `(cash_and_equivalents + marketable_securities + accounts_receivable) / total_current_liabilities`
- `working_capital_ratio`: `total_current_assets / total_current_liabilities`
- `net_working_capital`: `total_current_assets - total_current_liabilities`
- `return_on_assets`: `net_income / ((assets_current + assets_prior) / 2)`
- `free_cash_flow`: `operating_cash_flow - capital_expenditures`
- `inventory_turnover`: `cogs / ((inventory_begin + inventory_end) / 2)`
- `dividend_payout_ratio`: `dividends_paid / net_income`
- `retention_ratio`: `1 - dividends_paid / net_income`

These are not benchmark row hacks. They are formula-name, slot-frame,
EvidenceSpec, TransformSpec, and missing-fact retrieval capabilities. Runtime
missing-fact payloads for these formulas now trigger structured retrieval and
seed SEC companyfacts/companyconcept URLs for known issuers where possible.

Static FinanceBench `financebench_doc_retrieval.jsonl` formula coverage changed:

| Measure | Before | After |
| --- | ---: | ---: |
| Rows with recognized formula plan | `21/150` | `38/150` |
| Recognized missing-fact formulas with no `TransformSpec` | `0` | `0` |
| Rows with at least one `EvidenceSpec` | `150/150` | `150/150` |

Verification:

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "common_balance_sheet_ratio or common_cash_flow_and_turnover or computes_free_cash_flow_and_return_on_assets or quick_ratio_seeds"
.venv/bin/python -m py_compile kernel_v3/agent/runtime.py kernel_v3/finance/formula_planner.py kernel_v3/finance/task_compiler.py kernel_v3/finance/substrate_adapter.py tests/test_kernel_v3_finance_engine.py
git diff --check
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
```

Latest result: targeted common-formula tests `4 passed, 252 deselected`;
py_compile and `git diff --check` passed; full finance engine
`256 passed in 4.06s`; full FinanceBench tests `52 passed in 297.24s`.

## 2026-06-16 DPO And Capex/Revenue Average Follow-Up

The next question-only debug50 scan, with `gold_answer` / `evidence_excerpt`
excluded from implementation review, showed two common compute families still
compiled as lookup-only:

- days payable outstanding, including the FinanceBench definition using
  average accounts payable divided by `COGS + change in inventory`;
- multi-year average capex as a percent of revenue.

The planner/compiler now support these generic formula families:

- `dpo`: `fiscal_days * average accounts payable / COGS`
- `dpo_inventory_adjusted`:
  `fiscal_days * average accounts payable / (COGS + change in inventory)`
- `average_capex_to_revenue`: average of annual
  `capital_expenditures / revenue` over the target fiscal-year range

This adds formula-name detection, missing-slot plans, EvidenceSpec statement /
line-item targets, TransformSpec expressions, slot accepted attributes, and
ready-plan payloads when facts are already available. It is not a row-answer
table and does not contain benchmark answers.

Static question-only FinanceBench `financebench_doc_retrieval.jsonl` formula
coverage changed:

| Slice | Before | After |
| --- | ---: | ---: |
| `debug50` rows with recognized formula plan | `14/50` | `16/50` |
| `all150` rows with recognized formula plan | `38/150` | `43/150` |
| `all150` rows with at least one `EvidenceSpec` | `150/150` | `150/150` |

Verification, labeled as code-regression only:

```bash
.venv/bin/python -m py_compile kernel_v3/finance/formula_planner.py kernel_v3/finance/substrate_adapter.py kernel_v3/finance/task_compiler.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "dpo_inventory_adjusted or average_capex_to_revenue"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
git diff --check
```

Latest result: py_compile passed; targeted finance-engine slice
`3 passed, 256 deselected in 1.66s`; full finance engine
`259 passed in 3.88s`; full FinanceBench harness
`52 passed in 321.67s`; `git diff --check` passed. These are not live
benchmark scores.

## 2026-06-16 Live Provider Check

The latest live FinanceBench smoke used Windows `DEEPSEEK_API_KEY` from the
User environment, forced model-owned processor roles, enabled live retrieval,
and kept gold/reference material out of model context:

- output:
  `.state/kernel_v3/bench/finance/run_fb_debug_o000_l001_live_20260616_v1.jsonl`
- summary:
  `.state/kernel_v3/bench/finance/run_fb_debug_o000_l001_live_20260616_v1.summary.json`
- thread:
  `.state/kernel_v3/threads/finance-bench-0001-financebench_id_03029/thread.jsonl`
- item: `financebench_id_03029`
- result: `0/1`, `status=failed`, `reason=failure_report_not_final_answer`
- live retrieval telemetry: `fetches=48`, `download_mb=6.5`,
  `cache_hits=18`, `retrieval_runs=4`
- processor telemetry: `tokens=0`, `processor_ms=0`,
  `processor_error_counts={"provider_circuit_open": 14, "processor_budget_exceeded": 2}`

The root-cause processor journal entries are `ledger-117168`,
`ledger-117170`, `ledger-117193`, and `ledger-117195`. Their redacted
`previous_error_preview` is:

```text
deepseek HTTP 402: {"error":{"message":"Insufficient Balance","type":"unknown_error","param":null,"code":"invalid_request_error"}}
```

Windows environment presence was checked without printing secret values.
`DEEPSEEK_API_KEY` was present in the User environment; `OPENAI_COMPATIBLE_*`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DASHSCOPE_API_KEY`,
`QWEN_API_KEY`, and `OPENROUTER_API_KEY` were absent. Therefore the next live
benchmark requires either DeepSeek balance restoration or a configured
OpenAI-compatible live provider.

## What Is Not Proven Yet

- The post-2026-06-16 code changes do not yet have a fresh live accuracy number.
  The current Windows key is visible to WSL, but DeepSeek returned
  `HTTP 402: Insufficient Balance`, so the latest live smoke produced no model
  tokens and must be recorded as provider/account blockage.
- FinanceBench public 150 has not produced a valid held-out `test100` score.
  The project policy is still: use rows `0-49` as `debug50`; freeze the system;
  then run rows `50-149` as `test100` / `holdout100`.
- FinanceBench `debug50` snippets are useful for capability debugging, but they
  must not be reported as the held-out FinanceBench score.
- FAB public-style 27 has no public gold in the local artifact, so report
  workflow telemetry only unless a separate scoring reference is added.

## Next Real Benchmark Step

When a billable live provider is available again, run this as the next honest
measurement:

```bash
HOLO_V3_LIVE_MODEL=1 HOLO_V3_LIVE_FINANCE=1 \
.venv/bin/python -m kernel_v3.cli bench finance \
  --dataset data/bench/finance/financebench_doc_retrieval.jsonl \
  --split debug50 \
  --output .state/kernel_v3/bench/finance/run_fb_debug50_live_20260616.jsonl \
  --summary-output .state/kernel_v3/bench/finance/run_fb_debug50_live_20260616.summary.json \
  --execution-profile finance-fact-fast \
  --mission off \
  --parallel 1 \
  --research-profile finance_fundamentals \
  --thread-prefix fb-debug50-live-20260616
```

Only after reviewing `debug50` as the tuning slice and freezing the configuration:

```bash
HOLO_V3_LIVE_MODEL=1 HOLO_V3_LIVE_FINANCE=1 \
.venv/bin/python -m kernel_v3.cli bench finance \
  --dataset data/bench/finance/financebench_doc_retrieval.jsonl \
  --split test100 \
  --output .state/kernel_v3/bench/finance/run_fb_test100_live_20260616.jsonl \
  --summary-output .state/kernel_v3/bench/finance/run_fb_test100_live_20260616.summary.json \
  --execution-profile finance-fact-fast \
  --mission off \
  --parallel 1 \
  --research-profile finance_fundamentals \
  --thread-prefix fb-test100-live-20260616
```

That `test100` run is the number to put on the project scoreboard.
