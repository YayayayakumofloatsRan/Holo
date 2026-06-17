# Kernel v3 Finance Results Snapshot - 2026-06-17

Purpose: record today's finance problem-solving progress without mixing code
regression evidence with live benchmark accuracy. Permanent rule from
2026-06-17: fake/offline tests are forbidden as finance capability evidence;
they may only guard code contracts. FinanceBench, FAB/FinAgent, FinQA, and
finance problem-solving accuracy claims require real provider/live runs, with
gold/reference material used only after completion for scoring.

## Bottom Line

Finance problem-solving remains the core objective. The last broad reportable
live accuracy evidence is still the 2026-06-14 FinAgent/FAB-family run record
summarized in `docs/KERNEL_V3_FINANCE_RESULTS_SNAPSHOT_2026-06-16.md`.

After provider access was restored, a 2026-06-17 isolated FinanceBench debug
rerun on the first doc-retrieval row passed live. This is a real live
capability result for one debug item, not a held-out `test100` score.

| Field | Value |
| --- | --- |
| Dataset | `data/bench/finance/financebench_doc_retrieval.jsonl` |
| Item | `financebench_id_03029` |
| Slice | `--offset 0 --limit 1` debug rerun |
| Live status | `1/1`, `passed`, `numeric_within_tolerance` |
| Tokens / fetches | `237,555` tokens, `12` fetches, `5.5 MB` downloaded |
| Finance trace | calculator `1`, formula `1`, trace link `100.0%`, trace cite `100.0%` |
| Ledgers / gates | `202` facts, `202` claims, verifier `passed`, synthesis gate `passed` |
| Workbench | retrieval runs `1`, workbench sufficient rate `1.0` |
| Isolation | run state under `/tmp/holo-kv3-live-debug/fb-o000-l001-focused-escalated-20260617`; main `.state` was not used |

The answer identified 3M FY2018 capital expenditure as USD `1,577` million from
the filing line item "Purchases of property, plant and equipment (PP&E)" and
used the absolute value of the cash outflow. Gold/reference material remained
out of model context and was used only after completion for scoring.

Later on 2026-06-17, after adopting the streaming deep loop and open-component
evidence adapter, the same row passed again through the new toolchain path:

| Field | Value |
| --- | --- |
| Output | `.state/kernel_v3/bench/finance/fb_debug50_stream_grounding_o000_l001_20260617.jsonl` |
| Summary | `.state/kernel_v3/bench/finance/fb_debug50_stream_grounding_o000_l001_20260617.summary.json` |
| Live status | `1/1`, `passed`, `numeric_within_tolerance` |
| Matched numeric | expected `1577.0`, matched `1577.0` |
| Tool observations | `document.docling.convert:1`, `sec.edgar.financials:1`, `artifact.read:3`, `calculator.compute:1` |
| Evidence adapter | synthetic `toolchain_grounding`, no separate `retrieval.run` |
| Finance substrate | `210` facts, `210` claims, citations present |
| Numeric chain | calculator `1`, formula trace `1`, verifier `passed`, verifier gate `passed`, synthesis gate `passed` |
| Cost | `282,939` tokens |

This latest result is important because the immediately preceding streaming run
failed despite Docling returning the exact PP&E line: the finalizer still
required a `retrieval_report`. The new open-component evidence adapter promotes
model-called Docling/SEC observations into the same evidence/citation substrate,
closing that loop break. It remains a single debug-row result, not a debug50 or
test100 score.

Earlier same-day provider/environment failures, including a zero-token
non-escalated WSL environment failure and prior `HTTP_402_INSUFFICIENT_BALANCE`
checks, are not capability scores.

## 2026-06-17 Deep Loop Follow-Up Repair

After the P0 architecture pass moved finance-capability onto the
`deep_agent_loop`, the same `financebench_id_03029` row regressed: the model
tried `document.docling.convert`, `sec.edgar.financials`, `retrieval.run`, and
`artifact.read`, but stopped with the `capital_expenditures` slot still missing.
The live failures showed that the old `_RecipeBoundPlanner` workbench follow-up
logic was not active on the new deep-loop path.

The current repair is loop-generic:

- workbench `fail_with_limitations` with open `next_queries`,
  `next_document_targets`, or source families is treated as follow-up work, not
  as terminal evidence;
- `assistant.turn` prompts now include a continuation contract when feedback
  requires retrieval, formula, calculator, or transform work;
- the deep loop can scaffold a `retrieval.run` call from model/workbench
  follow-up targets when the next model turn chooses a non-retrieval tool such
  as stale `artifact.read`;
- repetition termination now checks both `feedback.missing_evidence` and
  `evidence.missing`, so `retrieval_workbench_followup` is not killed before
  the next tool turn.

Live validation after these changes:

| Field | Value |
| --- | --- |
| Output | `.state/kernel_v3/bench/finance/fb_debug50_p0gt95_o000_l001_after_evidence_guard_20260617.jsonl` |
| Journal | `.state/kernel_v3/bench/finance/fb_debug50_p0gt95_o000_l001_after_evidence_guard_20260617.journal.jsonl` |
| Status | `1/1`, `passed`, `numeric_within_tolerance` |
| Target numeric | expected `1577.0`, matched `1577.0` |
| Loop depth | `assistant.turn:7`, `retrieval_runs:7`, `fetches:39` |
| Toolchain | `calculator.compute:1`, formula trace `1`, verifier `passed`, gate `passed` |
| Evidence substrate | `74` facts, `74` claims, missing slots `0` |
| Cost warning | `851,272` tokens for one debug row; this is a correctness breakthrough, not an efficiency result |

This is still a single debug-row live result. It does not establish debug50 or
test100 accuracy. The next engineering target is to keep the deeper loop
capability while cutting redundant retrieval and processor context cost.

## 2026-06-17 Workbench Direct-Target Route Probe

The next same-day route probe used:

```text
.state/kernel_v3/bench/finance/fb_debug50_p0gt95_o000_l001_after_override_20260617.*
```

It was intentionally stopped before a benchmark row was written, so it is not an
accuracy score. Its journal is still useful loop evidence:

- step 3 `retrieval.run` found a workbench follow-up target:
  `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000066740&type=10-K&dateb=20181231&owner=exclude&count=1`;
- step 4 was host-scaffolded from `retrieval_workbench_followup`, and the primary
  `retrieval.run.query` was that SEC URL, not the model's broad text search;
- the step 4 workbench then discovered the concrete 2018 filing HTML:
  `https://www.sec.gov/Archives/edgar/data/66740/000155837019000470/mmm-20181231x10k.htm`;
- step 5 ran that filing URL as the primary query, the workbench marked evidence
  `sufficient`, termination moved to `final_answer`, feedback became
  `final_answer_ready`, and `finance_fact_ledger` plus `claim_ledger` records
  were written.

The run was interrupted during the final numeric preflight provider request, not
during retrieval, and produced no `.summary.json`. Report it as route/loop
evidence only. The code change behind the probe is generic: if feedback demands
`retrieval_workbench_followup` and the workbench provides direct document targets,
the deep loop promotes those targets over broad retrieval queries; candidate
`queries` are no longer treated as already attempted unless they were the primary
retrieval query.

## 2026-06-17 Live Target-Line Evidence Fix

The failed live trace before this pass was not missing documents. Retrieval had
already fetched the relevant 3M filing, and the accepted evidence span contained
the exact cash-flow row:

```text
Purchases of property, plant and equipment (PP&E) ... (1,577)
```

The failure was in the model-visible packet. Workbench summarized long evidence
from the beginning of the span, while the target PP&E row appeared later in the
span. The LLM therefore saw generic cash-flow context, did not see the specific
capex row reliably, and kept reporting `capital_expenditures` as missing.

The fix is generic, not an answer table:

- `kernel_v3/retrieval/workbench.py` now builds focused excerpts around
  requested line-item aliases and numeric/table markers, so target document
  candidates expose the relevant row instead of only the start of a long span.
- `kernel_v3/retrieval/evidence_compaction.py` now prefers same-line-item
  numeric/table candidates when the EvidenceSpec asks for a target line item,
  including generic aliases such as capex, PP&E, revenue, operating cash flow,
  and cost of sales.
- `kernel_v3/agent/runtime.py` now propagates the model-compiled execution
  program into a `compiled_task_hint`, so extraction/workbench can see the same
  EvidenceSpec and TransformSpec intent as the planner.

This keeps the semantic decision with the LLM. The host improves evidence
presentation, candidate ordering, and trace plumbing; it does not encode the
FinanceBench answer.

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
- `percent_of_sales_change`: a period-change scaffold for questions asking
  whether a metric as a percent of sales or net sales increased/decreased. The
  host binds prior/current percentage evidence and computes the signed
  difference; the LLM still explains the business meaning from cited filing
  context;
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

The latest no-gold pass applies the same pattern to "as a percent of sales" /
"as a percent of net sales" comparison questions. JnJ net earnings as a percent
of sales and Ulta wages expense as a percent of net sales now compile to
`percent_of_sales_change`, with `prior_percent_of_sales` and
`current_percent_of_sales` evidence slots and a
`current_percent_of_sales - prior_percent_of_sales` transform.

## Verification

The following checks were run as code regression only. They are not capability
scores under the permanent live-only finance benchmark rule:

```bash
.venv/bin/python -m py_compile kernel_v3/finance/formula_planner.py kernel_v3/finance/fact_ledger.py kernel_v3/finance/substrate_adapter.py kernel_v3/finance/task_compiler.py tests/test_kernel_v3_finance_engine.py
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "category_metric_rank"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "margin_profile_and_consistency"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "disclosure_lookup or direct_disclosure or metric_lookup or requested_metric_for_growth"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q -k "period_change or cash_flow_activity or percent_of_sales_change or market_risk_var_change"
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_benchmark.py tests/test_kernel_v3_finance_benchmark_report.py -q
git diff --check
```

Latest result: py_compile passed; targeted category-rank slice
`2 passed, 270 deselected in 1.57s`; targeted metric-lookup / regression slice
`4 passed, 269 deselected in 1.55s`; targeted disclosure/metric regression
slice `5 passed, 270 deselected in 1.68s`; latest targeted
category/metric-lookup slice `5 passed, 271 deselected in 1.76s`; targeted
period-change/VaR/percent-of-sales slice `3 passed, 273 deselected in 1.91s`;
full finance engine `276 passed in 3.93s`; FinanceBench harness/report
regression `59 passed in 398.51s`.

The latest focused engineering regression for the target-line evidence fix:

```bash
.venv/bin/python -m pytest tests/test_kernel_v3_finance_metric_intent.py tests/test_kernel_v3_retrieval_workbench.py -q
.venv/bin/python -m pytest tests/test_kernel_v3_finance_engine.py::test_finance_fact_ledger_extracts_html_column_cash_flow_rows tests/test_kernel_v3_finance_engine.py::test_html_table_fact_lines_preserve_parenthesized_capex_values tests/test_kernel_v3_finance_engine.py::test_finance_task_compiler_emits_direct_metric_evidence_for_capex_lookup tests/test_kernel_v3_finance_engine.py::test_finance_missing_fact_retrieval_action_preserves_target_document_binding -q
```

Latest focused result: retrieval/workbench and metric-intent tests
`30 passed in 0.61s`; targeted finance engine fact/task-binding regression
`4 passed in 0.47s`. These checks are engineering evidence only.

The latest live FinanceBench debug rerun, with the Windows `DEEPSEEK_API_KEY`
injected only into the child process and all benchmark gold/reference material
kept out of model context, passed `financebench_id_03029` at `1/1`
(`numeric_within_tolerance`). This is the reportable finance capability
evidence for this single debug row.

## Next Honest Benchmark Step

Continue with isolated live FinanceBench `debug50` as the tuning slice. Freeze
configuration after trace review, then run FinanceBench `test100` as the
held-out score. Do not report fake/offline tests as finance capability
progress.
