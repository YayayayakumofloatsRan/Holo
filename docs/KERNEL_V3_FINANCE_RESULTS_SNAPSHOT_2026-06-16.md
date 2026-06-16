# Kernel v3 Finance Results Snapshot - 2026-06-16

Purpose: record the finance problem-solving evidence that is already supported
by local benchmark artifacts, and separate it from claims that still need fresh
live reruns.

## Bottom Line

Finance problem-solving remains the core objective. The strongest local evidence
is still the 2026-06-14 live FinAgent/FAB-family run record, not today's code
changes alone.

Current fresh live rerun status on 2026-06-16: blocked by missing model
credentials. The latest smoke summary
`.state/kernel_v3/bench/finance/run_live_smoke_current_o000_l001_20260616.summary.json`
records `processor_error_counts={"missing_api_key_env": 1}`, `tokens=0`,
`retrieval_runs=0`, and `0/1` pass. This is an environment/configuration block,
not a capability score.

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

## What Is Not Proven Yet

- The post-2026-06-16 code changes do not yet have a fresh live accuracy number.
  The current shell has no model API key, so a live smoke produced
  `missing_api_key_env`.
- FinanceBench public 150 has not produced a valid held-out `test100` score.
  The project policy is still: use rows `0-49` as `debug50`; freeze the system;
  then run rows `50-149` as `test100` / `holdout100`.
- FinanceBench `debug50` snippets are useful for capability debugging, but they
  must not be reported as the held-out FinanceBench score.
- FAB public-style 27 has no public gold in the local artifact, so report
  workflow telemetry only unless a separate scoring reference is added.

## Next Real Benchmark Step

When a model key is available again, run this as the next honest measurement:

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
