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

DCF/LBO model traces now preserve full model schedules in `FormulaTrace`
diagnostics: DCF projections, terminal value, enterprise/equity bridge, optional
per-share output, and LBO debt-paydown / exit-equity / MOIC / IRR schedules.
These are deterministic calculator traces with explicit assumptions, not
unverified free-form synthesis. The verifier now recognizes model-output
diagnostics and explicit assumptions as supported calculator values, and the
host fallback can produce an assumption-labeled DCF/LBO summary when model
synthesis adds unsupported finance numbers.

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
