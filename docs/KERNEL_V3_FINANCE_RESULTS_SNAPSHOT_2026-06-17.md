# Kernel v3 Finance Results Snapshot - 2026-06-17

Purpose: record today's finance problem-solving progress without mixing code
regression evidence with live benchmark accuracy.

## Bottom Line

Finance problem-solving remains the core objective. The last reportable live
accuracy evidence is still the 2026-06-14 FinAgent/FAB-family run record
summarized in `docs/KERNEL_V3_FINANCE_RESULTS_SNAPSHOT_2026-06-16.md`.

Fresh FinanceBench live scoring is still blocked by provider account
availability. A minimal DeepSeek provider check on 2026-06-17 found the Windows
`DEEPSEEK_API_KEY` available to WSL, but the actual API call returned:

```text
HTTP_402_INSUFFICIENT_BALANCE
```

GitHub push is also still blocked by SSH authentication:

```text
git@github.com: Permission denied (publickey).
```

These are external blockers. They are not finance capability scores.

## 2026-06-17 Generic Formula Scaffold Follow-Up

The latest question-only scan of
`data/bench/finance/financebench_doc_retrieval.jsonl` excluded
`gold_answer` and `evidence_excerpt` from implementation review. It showed
several common compute families still compiling as lookup-only. The planner and
task compiler now add generic evidence/slot/transform scaffolds for:

- `effective_tax_rate_change`: current effective tax rate less prior effective
  tax rate, reported in percentage points;
- `net_working_capital` for positive-working-capital questions: total current
  assets less total current liabilities, leaving relevance and final judgment
  to the LLM;
- `interest_coverage_ratio`: adjusted EBIT or EBIT divided by interest expense;
- `unadjusted_ebitda`: operating income plus depreciation and amortization;
- `unadjusted_ebitda_less_capex`: operating income plus depreciation and
  amortization less capital expenditures;
- `asset_turnover`: revenue divided by average total assets;
- `average_cogs_to_revenue`: average annual COGS or cost of sales divided by
  annual revenue across the requested fiscal-year range;
- `liquidation_value_per_share`: total assets less total liabilities divided by
  shares outstanding;
- `debt_change`: current debt less prior debt for balance-sheet debt-change
  questions;
- `component_percent_of_total`: component amount divided by total amount, for
  patterns such as Q4 stock-repurchase spend as a percentage of total spend.

This continues the 2026-06-16 DPO and multi-year average capex/revenue scaffold
work. The host supplies auditable formulas, EvidenceSpec line-item targets, and
calculator-visible TransformSpecs; the LLM still owns semantic task compilation,
source choice, line-item binding, relevance assessment, and final explanation.
No benchmark answers are encoded.

Current static question-only FinanceBench formula coverage:

| Slice | Recognized formula rows | Rows with TransformSpec |
| --- | ---: | ---: |
| `debug50` | `19/50` | `19/50` |
| `test100` | `39/100` | `39/100` |
| `all150` | `58/150` | `58/150` |

Compared with the 2026-06-16 common-formula baseline, all150 recognized formula
coverage moved from `38/150` to `58/150`. This is only code-regression evidence
for the next live run, not a live benchmark score.

## Verification

The following checks were run as code regression only:

```bash
.venv/bin/python -m py_compile kernel_v3/finance/formula_planner.py kernel_v3/finance/substrate_adapter.py kernel_v3/finance/task_compiler.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "asset_turnover_and_average_cogs or liquidation_debt_change_component or asset_liquidation_and_component"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py -q
git diff --check
```

Latest result: py_compile passed; targeted finance-engine slice
`3 passed, 262 deselected in 1.79s`; full finance engine
`265 passed in 3.93s`; full FinanceBench harness
`52 passed in 306.67s`; `git diff --check` passed.

## Next Honest Benchmark Step

When a billable live provider is available, run `debug50` first as the tuning
slice. Freeze configuration after trace review, then run FinanceBench `test100`
as the held-out score. Do not report fake/offline tests as finance capability
progress.
