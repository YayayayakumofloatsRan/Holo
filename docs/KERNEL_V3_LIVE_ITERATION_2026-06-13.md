# Kernel v3 Live Iteration - 2026-06-13

## Goal

This iteration is capability-first. Holo Kernel v3 should behave as a general
LLM-driven intellectual workflow agent: the model owns semantic judgment, tools
provide execution surfaces, and the host validates provenance, safety, budget,
and hard contracts. Finance remains the pressure-test domain, not the product
boundary.

The user-facing priority is live problem-solving ability, not offline fake
tests. Benchmark scores should be read together with workflow traces: source
acquisition, ClaimLedger, SlotFrame, TransformPlan, calculator traces, verifier
gate, synthesis gate, and final answer.

## Changes In This Pass

- `finance-capability` now carries explicit LLM-owned judgment metadata.
  Strict capability mode treats missing `task.compile`, `finance.numeric_judge`,
  or model synthesis judgment as a real blocker instead of silently replacing
  the semantic decision with host heuristics.
- `task.compile` is strict in `finance-capability`: if the LLM compiler is not
  available, the runtime journals a `model_judgment_unavailable` program instead
  of fabricating a deterministic task program.
- Retrieval replan hints in strict LLM mode no longer inject host-selected query
  or source-family scaffolds. The host exposes diagnostics; the model must choose
  next queries, source families, document targets, or toolchain actions.
- `finance.numeric_judge` is treated as the semantic numeric verifier. The host
  deterministic verifier remains a hard provenance and safety gate, but its
  numeric matching is advisory when the model can classify core vs incidental
  numeric claims.
- Processor JSON normalization now accepts semantic aliases such as `reason`,
  `rationale`, `explanation`, or `summary` for `reason_summary` in model judge
  packets. This avoids losing useful LLM judgment due only to field-name drift.
- Strict finance synthesis now has a compact LLM rescue path: when initial
  synthesis fails but evidence/citations exist, the runtime builds a compact
  packet with ClaimLedger summaries, FormulaTrace summaries, and cited evidence,
  then asks the model to write a supported answer instead of returning a failure
  report.

## Live Results Captured

### FAB v2 dev10, finance-capability, parallel=10

Run:

`run_fabv2_dev10_capability_parallel10_judgefix`

Result summary:

- `overall_score=0.8752`
- `behavior_score=0.8333`
- `substrate_score=0.8111`
- `workflow_score=0.8563`
- `numeric_score=1.0`
- `claim_ledger_present_rate=1.0`
- `slot_frame_present_rate=1.0`
- `transform_plan_present_rate=1.0`
- `calculator_used_rate=0.5`
- `formula_trace_present_rate=0.5`
- `numeric_verifier_pass_rate=0.4`
- `synthesis_gate_pass_rate=0.5`
- `synthesis_gate_repair_rate=0.4`
- `unsupported_numeric_claim_rate=0.3`
- `average_answer_numeric_support_rate=0.9422`

Interpretation:

The generic workflow substrate is now reliably present on the curated dev10.
The weak points are final synthesis closure, calculator binding for some
valuation/transaction tasks, and unsupported numeric repair. This is no longer
a source-acquisition-only failure.

### FinanceBench doc_retrieval live10, finance-capability, parallel=10

Run:

`run_financebench_doc_live10_capability_parallel10_judgefix`

Result summary:

- Programmatic pass rate: `0/10`
- `claim_ledger_present_rate=0.9`
- `slot_frame_present_rate=0.9`
- `transform_plan_present_rate=0.9`
- `synthesis_gate_pass_rate=0.8333`
- `synthesis_gate_repair_rate=0.6667`
- `numeric_verifier_pass_rate=0.5`
- `citation_preservation_rate=0.5`
- `unsupported_numeric_claim_rate=0.1`
- `workflow_score=0.8714`
- `substrate_score=0.8286`

Interpretation:

FinanceBench doc retrieval is not solved. The official numeric scorer remains
at zero for this live10 slice, but the run is not a total agent failure:
most rows now produce claims, slots, transform plans, and synthesis gates. The
remaining gap is target-document table extraction plus answer numeric selection:
the agent often reaches the right source family and writes a plausible answer,
but it does not reliably extract or select the exact gold numeric row.

## Current Diagnosis

The current bottleneck is not simply "LLM intelligence." It is orchestration:

1. **Document/table grounding**: FinanceBench doc retrieval still often sees the
   filing/index/source shell without reliably lifting the target table row into
   ClaimLedger.
2. **Numeric selection**: The system may have many facts, but the answer path
   can choose a nearby or explanatory value instead of the benchmark target
   value.
3. **Synthesis/verifier closure**: Some runs produce rich claims and formula
   traces but stop as failure reports because the final answer packet fails or
   the verifier rejects incidental unsupported numbers.
4. **Live provider stability**: high-parallel live runs sometimes leave a worker
   without a final JSONL row. This needs more robust per-item worker isolation
   and progress visibility.

## Operating Rule For The Next Iteration

No more threshold-first search tuning. The host should not pretend that
thresholds are intelligence. The next iteration should continue the pivot:

- LLM decides task shape, source role, evidence usefulness, missing slots,
  transform intent, and whether an answer is semantically acceptable.
- Tools expose search/fetch/read/parse/script/calculate interfaces.
- Host validates provenance, IDs, citations, numeric trace support, policy, and
  budget.
- Failures must be visible in the workflow view, not hidden behind a silent loop.

## Next Work Queue

1. Keep parallel live batches running in small shards to avoid all-or-nothing
   worker hangs.
2. Add per-item live progress visualization for active benchmark workers.
3. Strengthen the compact LLM synthesis rescue on KHC/WSC/PFE-style failures.
4. Improve target-document table extraction and LLM-guided row selection for
   FinanceBench doc retrieval.
5. Keep a held-out validation split separate from tuning rows.
6. Generate a Windows-openable demo surface from WSL using `workflow-view` and a
   lightweight local web server.

## Demo Narrative

Holo Kernel v3 is best described as:

> A general LLM-driven intellectual workflow kernel with host-owned tools,
> provenance, verification, memory, and visualization. Finance is the first
> high-pressure domain pack used to expose whether the workflow actually works.

The strongest demo is not a single final answer. It is the internal flow:

question -> LLM task compiler -> toolchain/retrieval -> ClaimLedger -> SlotFrame
-> TransformPlan -> calculator trace -> LLM numeric judge -> verifier gate ->
synthesis gate -> final answer or diagnosed failure.

