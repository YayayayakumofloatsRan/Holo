# Kernel v3 Finance Results Snapshot - 2026-06-17

Purpose: record today's finance problem-solving progress without mixing code
regression evidence with live benchmark accuracy.

## Bottom Line

Finance problem-solving remains the core objective. The last reportable live
accuracy evidence is still the 2026-06-14 FinAgent/FAB-family run record
summarized in `docs/KERNEL_V3_FINANCE_RESULTS_SNAPSHOT_2026-06-16.md`.

Fresh FinanceBench live scoring is still blocked by provider account
availability. Minimal DeepSeek checks on 2026-06-17 found the Windows
`DEEPSEEK_API_KEY` available to WSL and injectable into the live model process,
but the actual API call returned:

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
  worst metric, including "biggest drop" / largest-decline variants. The host
  only prepares a ranked-category evidence slot and calculator-visible
  `max`/`min` transform over cited numeric rows; the LLM maps the extreme value
  back to the category, resolves ties or wording, and explains the final answer
  from filing evidence;
- `market_risk_var_change`: a period-change scaffold for VaR questions that
  ask whether risk increased/decreased compared with a prior period. The host
  binds prior/current value-at-risk evidence and computes the signed difference;
  the LLM interprets the result in the filing's market-risk context;
- `metric_lookup`: a generic filing-metric identity transform for direct
  line-item extraction questions. It covers requested single facts such as
  capital expenditures, net PP&E, accounts receivable/payable, inventories,
  COGS, net income, adjusted EBITDA, operating cash flow, dividends paid,
  restructuring costs, total assets/current assets/current liabilities, VaR,
  credit facilities, transaction proceeds/gains, expected benefit payments,
  separation/spin-off expected payments, and sales-change disclosures such as
  "real change in sales" excluding FX.
  The host binds the metric slot and optional calculator trace; the LLM still
  verifies the statement, period, unit, sign convention, and any explicit
  absence condition from cited evidence;
- `disclosure_lookup`: a generic evidence-only scaffold for qualitative filing
  questions where a numeric transform would be the wrong abstraction. It covers
  registered debt securities, dividend history, 8-K agenda summaries,
  acquisitions, industries, products/services, product revenue concentration,
  customers, geographies, customer retention, cyclicality, production rates,
  legal proceedings, dividends, governance/proxy items, shareholder voting,
  guidance, separations/discontinued operations, nonrecurring events, revenue
  and inventory drivers, expense ratio explanations, growth-profile evidence,
  restructuring liabilities, and remaining market-risk disclosures. The host
  prepares the EvidenceSpec and task type; the LLM reads cited evidence and owns
  the semantic conclusion.

The fact ledger also now canonicalizes investing cash flow, financing cash
flow, store-count, segment-income, EBITDAR, debt-securities, marketable-
securities, derivative-instrument, notional-value, accounts receivable/payable,
current-assets, dividends-paid, restructuring-cost, transaction-gain/proceeds,
VaR, credit-facility, and expected-benefit-payment metrics, and splits inline
`metric=... ; metric=...` fact segments even when the text does not include a
`facts=` wrapper.

This continues the 2026-06-16 DPO and multi-year average capex/revenue scaffold
work. The host supplies auditable formulas, EvidenceSpec line-item targets, and
calculator-visible TransformSpecs; the LLM still owns semantic task compilation,
source choice, line-item binding, relevance assessment, and final explanation.
No benchmark answers are encoded.

Current static question-only FinanceBench coverage:

| Slice | Recognized formula rows | Rows with EvidenceSpec |
| --- | ---: | ---: |
| `debug50` | `50/50` | `50/50` |
| `test100` | `100/100` | `100/100` |
| `all150` | `150/150` | `150/150` |

Compared with the 2026-06-16 common-formula baseline, all150 recognized formula
coverage moved from `38/150` to `150/150`. Compared with the previous
2026-06-17 metric-lookup checkpoint, it moved from `102/150` to `150/150` by
adding the generic disclosure scaffold and closing the remaining direct-metric
punctuation/wording gaps. This is only code-regression evidence for the next
live run, not a live benchmark score.

The latest follow-up inspected the `150/150` covered rows for weak structures
without consulting gold/reference answers. It moved Pfizer's "geographic region
with the biggest Q2 2023 year-over-year revenue drop" from a broad geography
disclosure slot to `category_metric_rank` with a `min(category_metric_values)`
transform and `geographic revenue` evidence target. It also moved Pfizer/Upjohn
"expect to pay to spin off" wording from generic spin-off disclosure to a direct
`metric_lookup` slot, `separation_payment`, targeting transaction/separation
note evidence. These changes improve live task structure; they are not answer
tables.

The next no-gold structural pass moved JPM's "did VaR decrease compared with
the same quarter in the prior year?" row from broad market-risk disclosure to
`market_risk_var_change`, with `market_risk_var_prior` and
`market_risk_var_current` evidence slots and a
`market_risk_var_current - market_risk_var_prior` transform. This gives the LLM
a signed numeric trace for the yes/no decrease judgment while leaving source
binding and interpretation model-owned.

## Verification

The following checks were run as code regression only:

```bash
.venv/bin/python -m py_compile kernel_v3/finance/formula_planner.py kernel_v3/finance/fact_ledger.py kernel_v3/finance/substrate_adapter.py kernel_v3/finance/task_compiler.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "category_metric_rank"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "margin_profile_and_consistency"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "disclosure_lookup or direct_disclosure or metric_lookup or requested_metric_for_growth"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "period_change or cash_flow_activity or market_risk_var_change"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q
git diff --check
```

Latest result: py_compile passed; targeted category-rank slice
`2 passed, 270 deselected in 1.57s`; targeted metric-lookup / regression slice
`4 passed, 269 deselected in 1.55s`; targeted disclosure/metric regression
slice `5 passed, 270 deselected in 1.68s`; latest targeted
category/metric-lookup slice `5 passed, 271 deselected in 1.76s`; targeted
period-change/VaR slice `3 passed, 273 deselected in 1.57s`; full finance
engine `276 passed in 5.13s`; FinanceBench harness/report regression
`59 passed in 397.74s`.

The live model smoke was also attempted with the Windows `DEEPSEEK_API_KEY`
injected into the WSL process and `HOLO_V3_LIVE_MODEL=1`. It reached the
DeepSeek provider and again failed with `deepseek HTTP 402: Insufficient
Balance`. No live FinanceBench score was produced.

## Next Honest Benchmark Step

When a billable live provider is available, run `debug50` first as the tuning
slice. Freeze configuration after trace review, then run FinanceBench `test100`
as the held-out score. Do not report fake/offline tests as finance capability
progress.
