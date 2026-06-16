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
  patterns such as Q4 stock-repurchase spend as a percentage of total spend;
- `cash_and_equivalents_change`: current cash and cash equivalents less prior
  cash and cash equivalents for drop/increase questions;
- `property_plant_and_equipment_change`: current net PP&E less prior net PP&E,
  including FY20/FY21 shorthand parsing;
- `store_count_change`: current store count less prior store count;
- `cash_flow_activity_comparison`: maximum signed amount across operating,
  investing, and financing cash-flow activities, leaving the activity-name
  conclusion and explanation to the LLM;
- `margin_profile_change`: ending annual margin less beginning annual margin
  for operating/gross margin profile and margin-driver questions;
- `margin_consistency_range`: maximum annual margin less minimum annual margin
  for historical gross-margin consistency questions. The host computes the
  range only; the LLM applies any explicit question criterion such as "roughly
  2%" and decides whether the metric is useful in context;
- `category_metric_rank`: a generic table-ranking scaffold for questions that
  ask which segment, region, product category, liability line, short-term
  investment type, or derivative instrument has the highest/lowest/largest/
  worst metric. The host only prepares a ranked-category evidence slot and
  calculator-visible `max`/`min` transform over cited numeric rows; the LLM
  maps the extreme value back to the category, resolves ties or wording, and
  explains the final answer from filing evidence.

The fact ledger also now canonicalizes investing cash flow, financing cash
flow, store-count, segment-income, EBITDAR, debt-securities, marketable-
securities, derivative-instrument, and notional-value metrics, and splits
inline `metric=... ; metric=...` fact segments even when the text does not
include a `facts=` wrapper.

This continues the 2026-06-16 DPO and multi-year average capex/revenue scaffold
work. The host supplies auditable formulas, EvidenceSpec line-item targets, and
calculator-visible TransformSpecs; the LLM still owns semantic task compilation,
source choice, line-item binding, relevance assessment, and final explanation.
No benchmark answers are encoded.

Current static question-only FinanceBench formula coverage:

| Slice | Recognized formula rows | Rows with TransformSpec |
| --- | ---: | ---: |
| `debug50` | `29/50` | `29/50` |
| `test100` | `55/100` | `55/100` |
| `all150` | `84/150` | `84/150` |

Compared with the 2026-06-16 common-formula baseline, all150 recognized formula
coverage moved from `38/150` to `84/150`. This is only code-regression evidence
for the next live run, not a live benchmark score.

## Verification

The following checks were run as code regression only:

```bash
.venv/bin/python -m py_compile kernel_v3/finance/formula_planner.py kernel_v3/finance/fact_ledger.py kernel_v3/finance/substrate_adapter.py kernel_v3/finance/task_compiler.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "category_metric_rank"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "margin_profile_and_consistency"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q
git diff --check
```

Latest result: py_compile passed; targeted category-rank slice
`2 passed, 270 deselected in 1.57s`; full finance engine
`272 passed in 5.34s`; FinanceBench harness/report regression
`59 passed in 399.94s`; `git diff --check` passed.

## Next Honest Benchmark Step

When a billable live provider is available, run `debug50` first as the tuning
slice. Freeze configuration after trace review, then run FinanceBench `test100`
as the held-out score. Do not report fake/offline tests as finance capability
progress.
