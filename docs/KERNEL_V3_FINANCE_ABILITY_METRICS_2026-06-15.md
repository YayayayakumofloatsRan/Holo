# Kernel v3 Finance Ability Metrics - 2026-06-15

## Purpose

This note separates single-item debugging from actual ability evidence. A one-question smoke test can locate agent-loop bugs, but reportable finance capability must be judged across datasets, splits, workflow types, tool traces, numeric accuracy, and cost.

Gold/reference answers are post-run scoring material only. They are not placed in planner, retrieval, slot-bind, calculator, synthesis, memory, or prompt context.

## Available Local Finance Benchmark Sets

| Dataset | Items | Gold / scoring | Current role |
|---|---:|---|---|
| `data/bench/finance/fabv2_dev10.jsonl` | 10 | `fabv2_dev10.gold.jsonl` has expected numerics, required traces, sources, slots, transforms, and dealbreakers | Curated development harness for workflow pressure tests. |
| `data/bench/finance/fabv2_public.jsonl` | 27 | no public gold | Public behavior/substrate/cost/failure-taxonomy health check. |
| `data/bench/finance/financebench_doc_retrieval.jsonl` | 150 | in-row `gold_answer` plus `financebench_doc_retrieval.gold.jsonl` workflow/source sidecar | FinanceBench source-acquisition and filing-metric benchmark. |
| `data/bench/finance/holo_finance_workflow_challenge.jsonl` | 50 | no answer gold | Internal workflow challenge set for coverage/failure taxonomy. |

Checked-in unique prompt count is `237`: `160` items are answer-scored or annotation-scored, and `77` items are no-gold workflow/substrate/cost probes.

## Coverage Shape

The checked-in sets cover these finance task families:

| Task family | Representative questions | Local coverage |
|---|---|---:|
| Source-grounded filing research | SEC/company filing lookup, target document acquisition, line-item extraction | 150 FinanceBench doc-retrieval items plus source-grounded public items |
| Multi-entity computation | Compare Home Depot vs Lowe's DIO and compute the difference | FAB dev + challenge |
| Reconciliation / bridge analysis | Adjusted EBITDA bridge, add-back trend, reported-to-adjusted metric movement | FAB dev + challenge |
| Event / transaction analysis | Pfizer-Seagen transaction multiple, filing/event disclosure lookup | FAB dev + challenge + public |
| Modeling-lite | DCF, LBO, valuation assumptions with explicit source support | FAB dev + challenge + public |
| Valuation and coverage ratios | EV/EBITDA, interest coverage, capital intensity, fixed asset turnover | FAB dev + challenge + FinanceBench |
| Regulatory / specialized ratios | bank capital/regulatory-style ratios and domain-specific metrics | FAB dev + challenge |
| Purchase price allocation / goodwill | acquisition accounting, goodwill/intangible allocation | FAB dev + challenge |

## Strongest Existing Live Evidence

These are existing local live run summaries, not offline fake tests.

| Run | Items | Pass / score | Notes |
|---|---:|---|---|
| `run_finagent_full40_after_nonitemized_headline_live_20260614.summary.json` | 40 | pass_rate `0.95`, numeric_accuracy `0.9487` | Best full40 strict live run before rescore. |
| `run_finagent_full40_after_nonitemized_headline_live_20260614.rescored.summary.json` | 40 | pass_rate `0.975`, numeric_accuracy `0.9487` | Same live outputs rescored after scorer/headline correction. |
| `run_full40_previous_failures_after_nonitemized_headline_live.summary.json` | 12 | pass_rate `1.0`, numeric_accuracy `1.0` | Historical failure-regression slice closed end to end. |
| `run_failure_regression_full11_after_annual_margin_rank_live.summary.json` | 11 | pass_rate `1.0`, numeric_accuracy `1.0` | Focused failure-regression slice closed. |
| `run_global_finagent_limit10_live_20260613.summary.json` | 10 | pass_rate `0.8`, numeric_accuracy `0.8` | FinAgent dev-style 10-item slice. |
| `run_global_finagent_test10_live_20260613.summary.json` | 10 | pass_rate `0.8`, numeric_accuracy `0.8` | Separate 10-item test/holdout slice. |
| `run_metric_disambiguation_live14_20260613.summary.json` | 14 | pass_rate `0.7857`, numeric_accuracy `0.7857` | Metric/line-item disambiguation slice. |
| `run_financebench_doc_live10_capability_parallel_v2.summary.json` | 10 | pass_rate `0.5`, numeric_accuracy `0.5`, overall `0.8336` | Best local FinanceBench doc-retrieval live10 in this snapshot. |
| `run_financebench_doc_live10_capability_doclink_v2.summary.json` | 10 | pass_rate `0.4`, numeric_accuracy `0.4`, overall `0.7862` | Follow-up target-document/link acquisition run. |
| `run_fabv2_dev10_capability_parallel10_judgefix.summary.json` | 10 | overall `0.8752`, workflow `0.8563`, substrate `0.8111`, numeric `1.0` | FAB v2 dev10 workflow/scaffold ability score; official pass is not the right headline because this set is annotation-heavy. |
| `run_dev10_event_resolver_v1.workflow_scored.summary.json` | 10 | overall `0.9114`, workflow `0.8399`, substrate `0.8889`, numeric `1.0` | Best dev10 workflow-score snapshot in this state tree. |

Do not merge fake/oracle control experiments into this live scorecard. Files containing `fake` or oracle evidence are useful for harness debugging but not for real finance ability claims.

## Ability Metrics

The finance subsystem should be judged on a bundle, not a single pass rate:

| Metric | What it measures | Why it matters |
|---|---|---|
| `pass_rate` | Post-run answer scoring against gold/reference signals | Headline correctness where gold exists. |
| `numeric_accuracy` | Numeric target within tolerance | Core financial calculation and extraction accuracy. |
| `dev_annotation_score.overall_score` | Average of behavior, numeric, substrate, and workflow annotation scores | Captures hard workflow quality when pure answer gold is insufficient. |
| `workflow_score` | Required slots, transforms, source families, evidence terms, dealbreakers | Measures whether the agent solved the finance workflow, not just wrote a plausible answer. |
| `substrate_score` | Required trace/substrate events such as retrieval, claim ledger, slot frame, verifier, synthesis, citation | Measures whether Kernel v3's agent loop and tool substrate were actually used. |
| `calculator_used_rate` and `formula_trace_present_rate` | Calculator/tool trace coverage | Ensures numerical work is tool-backed and auditable. |
| `citation_present_rate` and source-family hits | Source grounding | Prevents unsupported finance answers. |
| `average_total_tokens`, cache-hit metrics, retrieval counts | Cost and efficiency | Needed for persistent deployment and large benchmark runs. |
| failure reason counts | Dominant bottleneck by item cluster | Converts benchmark results into the next engineering target. |

## Current 2026-06-15 Single-Item Debug Runs

These runs diagnose the current strict finance-capability agent loop on `fabv2-hd-low-dio`. They should not be presented as broad ability metrics.

| Run | Overall | Calculator trace | Main finding |
|---|---:|---:|---|
| `run_finance_cache_live_20260615_v4.summary.json` | `0.7892` | `1.0` | Calculator path existed, but fact binding chose wrong period values. |
| `run_finance_slotbind_live_20260615_v2.summary.json` | `0.7189` | `0.0` | Slot-bind failed because schema rejected model output shape. |
| `run_finance_slotbind_schema_live_20260615_v1.summary.json` | `0.8039` | `1.0` | Schema normalization fixed; calculator trace required dealbreaker passed. |
| `run_finance_chain_compact_live_20260615_v1.summary.json` | `0.7189` | `0.0` | Compact synthesis worked, but slot-bind model JSON was malformed/truncated, so calculator was not reached. |

## Current Interpretation

Kernel v3 already has reportable multi-question finance evidence:

- Strong FinAgent-style live evidence: full40 strict `95.0%`, rescored `97.5%`, separate dev/test 10-item slices at `80%`.
- Strong failure-regression evidence: 11/11 and 12/12 focused live slices.
- Moderate FinanceBench doc-retrieval evidence: best local live10 is `5/10`, with high workflow/substrate scores but incomplete numeric accuracy.
- FAB v2 dev10 currently works best as a workflow/substrate harness rather than a solved official accuracy benchmark.

The active 2026-06-15 code line is not yet ready for a new broad rerun because `finance.slot_bind` JSON reliability is now the immediate bottleneck. Running 10-40 items before fixing that would spend tokens measuring the wrong failure.

## Reporting Position

For the talk/report, the honest headline is:

- Local finance question bank: `237` unique checked-in prompts.
- Gold/annotation-scored local prompts: `160`.
- Historical best real live multi-item score: FinAgent-style full40 `95.0%` pass, `94.87%` numeric accuracy; rescored same outputs `97.5%` pass.
- Harder FinanceBench doc-retrieval status: live10 best `50%` pass / `50%` numeric, but workflow/substrate score already reaches `0.8336`, so the failure is concentrated in acquisition/binding/synthesis details rather than total harness collapse.
- Current active Kernel v3 strict-finance branch: architecture is cleaner and more LLM-owned, but the immediate blocker is structured `finance.slot_bind` output reliability. Fix that before spending tokens on the next broad run.

## Metrics To Report Going Forward

For every multi-item run, report:

- `item_count`
- `pass_rate`
- `numeric_accuracy`
- `dev_annotation_score.overall_score`, when available
- `workflow_score`
- `substrate_score`
- `calculator_used_rate`
- `formula_trace_present_rate`
- `average_total_tokens`
- `average_retrieval_runs`
- failure reason counts
- per-workflow-type scores

For no-gold sets, do not report accuracy. Report behavior/substrate/workflow/cost/failure taxonomy only.

## Immediate Next Action

Completed in the current code line:

1. Stabilized `finance.slot_bind` JSON output by reducing output verbosity and forbidding long prose in `reason`.
2. Increased/adapted structured-output budget for `task.compile` and `finance.slot_bind`, where live traces showed JSON truncation.
3. Added a model-repair path for malformed slot-bind JSON so a nearly valid model decision can be repaired into schema instead of dropping calculator execution.
4. Verified the local regression suite: `219 passed` across finance engine, execution profile, processor usage, and retrieval workbench tests.

Next scoring step:

1. Run a single live smoke on `fabv2-hd-low-dio` to verify the real provider now reaches final calculator-visible DIO formulas.
2. If the smoke is stable, run:
   - `fabv2_dev10` 10 items for workflow score and dev-gold numeric checks.
   - `financebench_doc_retrieval` 10-item live slice for true source-acquisition generalization.
   - optionally a no-gold `fabv2_public` behavior run for substrate/tool health.
