# Holo Kernel v3 Finance Workflow RC

Date: 2026-06-11

This document freezes the current Finance Workflow release-candidate baseline.
It is not an official Finance Agent Benchmark score. It is a reproducible
handoff for the Holo Kernel v3 workflow spine:

```text
task -> slot frame -> evidence policy -> claim ledger
     -> transform plan / calculator trace -> verifier gate
     -> synthesis gate -> cited final answer or structured limitation
```

## Frozen Reports

The markdown reports were regenerated from the latest saved run JSONL files:

```text
.state/kernel_v3/bench/finance/run_stable4_event_resolver_v1.report.md
.state/kernel_v3/bench/finance/run_dev10_event_resolver_v1.report.md
.state/kernel_v3/bench/finance/run_dev10_event_resolver_v1.workflow_report.md
.state/kernel_v3/bench/finance/run_public27_workflow_v1.report.md
```

The `.state` files are runtime artifacts. This tracked document is the compact
GitHub-facing baseline.

## Headline Baseline

| Slice | Status | Headline |
| --- | --- | --- |
| stable4 showcase | closed workflow demo | overall `0.9603`, substrate `0.9167`, numeric `1.0`, citation `1.0` |
| curated dev10 live | scored regression | overall `0.9056`, substrate `0.8`, numeric `1.0`, citation-present `0.6` |
| dev10 workflow rescore | stricter trace score | overall `0.9114`, workflow `0.8399`, substrate `0.8889`, citation preservation `0.6` |
| public27 | ungraded health check | claim/slot/transform `0.6296`, citation preservation `0.2593`, synthesis-gate pass `0.1111` |

Stable4 covers HD/LOW DIO, KHC adjusted EBITDA bridge, PFE/Seagen transaction
multiple, and WSC adjusted EBITDA add-back trend. It is the showcase set, not a
generalization claim.

Public27 has no public gold and must remain a behavior/substrate/cost health
check. Do not report it as accuracy.

Gold-backed public benchmark support now starts with FinanceBench and FinQA:
`bench finance-import --benchmark financebench` supports `oracle_evidence`,
`doc_retrieval`, and `question_only` modes, while `--benchmark finqa` supports
`oracle_context` and `question_only`. The first reported FinanceBench run should
start with `oracle_evidence`, then compare `doc_retrieval` to measure source
acquisition instead of only answer synthesis.

The import path now also supports `--annotation-output`, producing a post-run
`--dev-gold` sidecar from the normalized dataset. The sidecar includes workflow
requirements, source requirements, expected traces, dealbreakers, and numeric
expectations extracted from reference answers. Reference answers and
justifications remain scoring-only and are not inserted into prompts.
`bench finance-fetch` can now fetch built-in public files for FinanceBench,
FinQA, and FAB v2 public into `data/raw` and optionally normalize them plus
write manifest/annotation sidecars in the same command. Use this to start the
first FinanceBench oracle-evidence and FinQA oracle-context runs when raw files
are absent locally.

2026-06-11 smoke verification has exercised that path against real public
files: FinanceBench merged rows downloaded `958,087` bytes and normalized
`5/5` oracle-evidence smoke rows with `0` skipped; FinQA `dev` downloaded
`10,954,658` bytes and normalized `5/5` oracle-context smoke rows with `0`
skipped. Both wrote `.gold.jsonl` sidecars. This verifies data acquisition and
normalization only; live model scoring for FinanceBench-150 and FinQA subsets is
still the next required benchmark step.

FinQA oracle-context rows now carry generic `numeric_reasoning` workflow
annotations instead of plain QA metadata: context/input/formula/unit slots,
provided-report-context evidence policy, expected calculator/verifier/synthesis
traces, and scoring-only reference program policy.

The first gold-backed oracle smoke after this import work is now closed for
FinanceBench source-grounded extraction. `oracle_evidence` is promoted inside
runtime to citable retrieval evidence before finalization, so the task can
finish from benchmark-provided source excerpts without live retrieval and
without seeing the reference answer. The first FinanceBench oracle item
(`run_financebench_oracle_smoke1_after_fallback_synthesis_gate`) passes in a
no-network fake-processor smoke with numeric accuracy `1.0`, citation
preservation `1.0`, answer numeric support `1.0`, and
claim/slot/transform/verifier/synthesis-gate presence `1.0`.
FinQA `oracle_context` now uses the same source/context path plus a
table-average calculator preflight. The first FinQA oracle-context item
(`run_finqa_oracle_smoke1_after_table_average_synthesis_gate`) passes with one
`calculator.compute` trace, one formula trace, verifier-gate pass,
synthesis-gate pass, citation preservation `1.0`, and annotation overall /
workflow / substrate / numeric scores of `1.0`. This is a single-item
oracle-context smoke, not a broad FinQA subset score.

A follow-up FinQA oracle-context subset diagnostic ran `20` local `dev` rows
without network access and without exposing gold/reference programs to prompts
(`run_finqa_oracle20_confirm_formula_patterns_v1`). Generic table/text
arithmetic preflight now binds several recurring numeric-reasoning operations:
table averages, indexed cumulative return, percentage-of-total, period change,
simple projection, and pretax/after-tax difference. The subset result is pass
rate / numeric accuracy `0.30`, calculator-used / formula-trace rates `0.60`,
substrate score `0.925`, workflow score `0.96`, citation preservation `0.95`,
synthesis-gate pass `1.0`, and unsupported numeric claim rate `0.0`. Treat this
as an oracle-context engineering diagnostic; the remaining failures are still
formula-binding and target-cell-selection gaps.

Public gold-backed baselines have now started and are summarized in
`docs/KERNEL_V3_PUBLIC_BENCHMARK_BASELINES_2026-06-11.md`.
FinanceBench-150 `oracle_evidence` no-network/fake-processor baseline
(`run_financebench_150_oracle_evidence_fake_v1`) produced pass rate `0.20`,
numeric accuracy `0.2381`, workflow score `0.9132`, substrate score `1.0`,
citation preservation `0.8733`, and unsupported numeric claim rate `0.1067`.
This is not a live-model leaderboard score; it is the first full public
gold-backed oracle-evidence substrate baseline.

FinanceBench `doc_retrieval` now has two deliberately separated records. The
full 150-row fake/no-network run
(`run_financebench_150_doc_retrieval_fake_v1`) is a negative control, not a
capability score: with only document metadata and no live acquisition, pass rate
is `0.0067`. A small true live probe
(`run_financebench_doc_retrieval_live_limit3_v1`) performed retrieval
(`1.3333` average retrieval runs; `8` to `16` fetches per item) but still scored
`0/3` because retrieved sources were not converted into citable finance facts or
calculator inputs. This is the current FinanceBench source-acquisition /
document-extraction gap.

The subsequent Retrieval Workbench probe proved that the first doc-retrieval
item can now produce citable facts and claims, but it exposed a narrower
primary-source numeric binding failure: the answer path accepted secondary
StockAnalysis current cash-flow data (`899M`) instead of the target FY2018
10-K cash-flow statement capex row (`1577M`). Issue #3 P0 addresses that
specific class of error by adding `target_document_binding` to workbench
packets, target-table extraction windows, and a host-owned
`primary_source_numeric_binding` resolver that rejects secondary/current facts
when the benchmark requires the target primary filing/period/statement/line
item. The narrow live1 validation is now closed:
`run_financebench_doc_live1_binding_v7` passed the first FinanceBench
doc-retrieval item with `numeric_within_tolerance`, `retrieval_runs=1`,
`facts=114`, `claims=114`, citation preservation `1.0`, numeric verifier /
verifier gate / synthesis gate all `passed`, unsupported numeric claim rate `0`,
and answer numeric support `100%`. The follow-up
`run_financebench_doc_live3_binding_v1` is `1/3`; all three items reached the
generic substrate, while items 2-3 now fail at unsupported numeric synthesis.
This is not yet a solved FinanceBench claim, but the original secondary-current
`899M` support failure is closed for the target live1 item.

FinQA `dev` oracle-context `100` no-network/fake-processor baseline
(`run_finqa_dev_oracle100_fake_v1`) produced pass rate / numeric accuracy
`0.15`, workflow score `0.925`, substrate score `0.8816`,
calculator/formula-trace rate `0.37`, citation preservation `0.92`, and
unsupported numeric claim rate `0.06`.

DCF/LBO model traces now preserve full model schedules in `FormulaTrace`
diagnostics: DCF projections, terminal value, enterprise/equity bridge, optional
per-share output, and LBO debt-paydown / exit-equity / MOIC / IRR schedules.
These are deterministic calculator traces with explicit assumptions, not
unverified free-form synthesis. The verifier now recognizes model-output
diagnostics and explicit assumptions as supported calculator values, and the
host fallback can produce an assumption-labeled DCF/LBO summary when model
synthesis adds unsupported finance numbers.
The calculator result now follows the requested modeling output where possible:
DCF selects enterprise value, equity value, or equity value per share; LBO
selects sponsor IRR, MOIC, or exit equity value.

## Workflow 50

`data/bench/finance/holo_finance_workflow_challenge.jsonl` is a 50-item
workflow challenge set. It is organized by workflow shape rather than company:

```text
compute_compare
reconciliation
event_transaction
valuation_multiple
coverage_ratio
earnings_analysis
disclosure_diff
market_event_analysis
modeling_lite
regulatory_ratio
```

Each item is meant to pressure a reusable Holo workflow primitive: slot filling,
source acquisition, claim extraction, transform planning, calculator traces,
verifier gates, synthesis gates, or failure recovery. The file is a trace-quality
suite, not a scored public benchmark.

## Current Gaps

The next iteration should stay narrow:

1. Public27 qualitative disclosure tasks need generic source-grounded
   `ClaimLedger`, `SlotFrame`, `TransformPlan`, and citation traces even when no
   numeric formula is applicable.
2. Numeric tasks with partial support need SynthesisGate repair. Unsupported
   material numbers should be removed, converted to limitations, or backed by a
   `ClaimLedger`, `FormulaTrace`, or explicitly labeled assumption.
3. Fallback answers must preserve citation refs when evidence exists.
4. Modeling-lite answers must distinguish retrieved facts from assumptions.

## Failure Taxonomy

Classify failures before adding domain logic:

```text
source_acquisition
fetch_or_parser
claim_ledger_extraction
missing_slot
formula_binding
verifier_policy
synthesis_gate
model_json_repair
assumption_labeling
cost_budget
```

The current public27 failure clusters are `all_evidence_rejected`,
`coverage_gap`, and `finance_numeric:unsupported_answer_number`.

## RC Hardening Added

This RC hardening pass adds two narrow reliability improvements:

- Generic source-grounded retrieval finalization now writes a domain-neutral
  `claim_ledger`, `slot_frame`, and `transform_plan` for qualitative research
  tasks whenever retrieval evidence exists.
- Finance SynthesisGate fallback now strips unsupported material numeric claims,
  preserves existing citation refs, and can return a conservative limitation
  answer even when no calculator trace is available.

Targets for the next live public27 rerun:

```text
citation_preservation >= 0.6
synthesis_gate_pass_rate >= 0.4
unsupported_numeric_claim_rate <= 0.2
claim/slot/transform_present_rate >= 0.75
```
