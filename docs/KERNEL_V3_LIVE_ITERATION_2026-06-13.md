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
- The `finance-capability` finalization path is now explicitly LLM-first. When
  planned retrieval coverage is incomplete but the run has citable evidence, the
  host treats missing subgoals as diagnostics and lets model synthesis produce a
  best-supported answer with limitations. The deterministic numeric verifier
  remains a provenance/calculator diagnostic, but `finance.numeric_judge` can
  semantically accept a core answer when it answers the question, requires no
  further work, and has no unsupported core numeric values.
- Planner context now includes a finance analyst work template and standard
  tool interface contract for `retrieval.run`, `calculator.compute`, and
  `respond`. In strict LLM mode, host retrieval payload supervision preserves
  the model-selected query/source strategy after applying schema/profile/budget
  defaults instead of rewriting the research move from host hints.

## Live Results Captured

### Demo-ready hard FinanceBench case: Activision fixed asset turnover

Promoted demo run:

`run_demo_financebench_activision_fat_live_20260613`

Task:

`financebench_id_02987` asks for Activision Blizzard's FY2019 fixed asset
turnover ratio, defined as FY2019 revenue divided by average PP&E between
FY2018 and FY2019, rounded to two decimals, using the supplied 2019 10-K source
URL as primary evidence.

Result:

- Strict benchmark status: `passed`
- Programmatic pass rate: `1/1`
- Numeric accuracy: `1.0`
- Dev annotation overall score: `1.0`
- Workflow score: `1.0`
- Substrate score: `1.0`
- Matched answer: `24.26`
- Retrieval runs: `1`
- Fetch attempts: `12`
- Finance facts: `245`
- Claim ledger records: `245`
- Transform plans: `1`
- Citation present rate: `1.0`
- Synthesis gate pass rate: `1.0`

User-visible answer:

Activision Blizzard FY2019 fixed asset turnover is `24.26`, using FY2019
revenue of `$6.489B`, FY2019 PP&E net of `$253M`, FY2018 PP&E net of `$282M`,
and average PP&E of `$267.5M`.

Why this is the current demo case:

- It is source-grounded against a real 10-K document URL from FinanceBench.
- The run exercises the intended Kernel v3 loop: LLM semantic intake and
  planning, live retrieval, evidence extraction, workbench judgment,
  ClaimLedger, SlotFrame, TransformPlan, synthesis repair, citations, and
  post-run benchmark scoring.
- It is not a table lookup: the gold numeric value is in
  `financebench_doc_retrieval.gold.jsonl` and is used only after the run by the
  scorer.
- The dashboard is served at `http://localhost:8787/` from WSL and defaults to
  this run for recording.
- The dashboard now supports item-level selection through `item_id`. For a
  stronger trace view during recording, select
  `run_financebench_doc_live10_capability_parallel_v2` with
  `item_id=financebench_id_02987`; that record shows 15 calculator calls, 738
  finance facts, 1048 citations, and numeric verifier `passed`.

Stability evidence:

- Current single-item live demo: `run_demo_financebench_activision_fat_live_20260613`
  passed with `overall_score=1.0`.
- Prior live capability batches also contain successful passes for the same
  Activision fixed-asset-turnover item:
  `run_financebench_doc_live10_capability_parallel_v2` and
  `run_financebench_doc_live10_capability_doclink_v2`.
- A DeepSeek Pro/high repeat attempted after the demo pass retrieved heavily
  (`retrieval_runs=3`, `finance_facts=735`) but failed during model synthesis
  after provider errors/circuit-open behavior, so it is recorded as an
  operational provider failure, not as promoted capability evidence.
- A later flash repeat was blocked immediately by DeepSeek `HTTP 402:
  Insufficient Balance`, so additional live-repeat evidence requires provider
  balance restoration.

Related search-loop improvement:

The difficult FAB v2 HD/LOW DIO task is retained as a search stress case.
This pass fixed an important loop issue: when the LLM retrieval workbench says
`decision=continue`, the outer workloop no longer finalizes early from partial
evidence. The host now routes the LLM workbench next move back through the
standard `retrieval.run` interface. On
`run_demo_fabv2_hd_low_dio_flash_workbenchfollow_20260613`, the loop performed
two retrieval runs and executed LOW-oriented follow-up queries. The item still
does not pass because LOW COGS and calculator binding remain incomplete; it is
therefore not the recording demo, but it is useful evidence that the agent loop
is moving toward model-owned search rather than host threshold rules.

### Global FinAgent FE live10 dev/test split

Runs:

- Dev/high-score slice: `run_global_finagent_limit10_live_20260613`
- Test/holdout slice: `run_global_finagent_test10_live_20260613`

Both runs used live DeepSeek generation plus live web/source retrieval. The
gold/reference records were used only by the scorer after each item completed;
they were not injected into the agent loop.

Dev/high-score slice summary:

- Strict programmatic score: `8/10`
- Post-run reasonable/source-grounded LLM judge: `8/10`
- `citation_present_rate=1.0`
- `citation_preservation_rate=1.0`
- `claim_ledger_present_rate=1.0`
- `slot_frame_present_rate=1.0`
- `transform_plan_present_rate=1.0`
- `numeric_verifier_pass_rate=1.0`
- `synthesis_gate_pass_rate=1.0`
- `unsupported_numeric_claim_rate=0.0`
- `average_answer_numeric_support_rate=1.0`

Test/holdout slice summary:

- Strict programmatic score: `8/10`
- Post-run reasonable/source-grounded LLM judge: `8/10`
- `citation_present_rate=1.0`
- `citation_preservation_rate=1.0`
- `claim_ledger_present_rate=1.0`
- `slot_frame_present_rate=1.0`
- `transform_plan_present_rate=1.0`
- `numeric_verifier_pass_rate=1.0`
- `synthesis_gate_pass_rate=1.0`
- `unsupported_numeric_claim_rate=0.0`
- `average_answer_numeric_support_rate=1.0`

The dev/high-score failures are honest capability gaps rather than scoring
noise:

- `FE_006` Salesforce: the agent refused to answer because it did not close the
  revenue evidence path; the expected answer is about `$34.8B`.
- `FE_009` Goldman Sachs: the agent selected a nearby derivative-sales metric
  instead of net revenues; the expected answer is about `$53.512B`.

The test/holdout failures are also useful diagnostics:

- `FE_015` Pfizer: the agent failed to surface the 2024 revenue value, about
  `$63.6B`, and returned a limitation answer.
- `FE_020` Chevron: the agent answered total revenues including broader line
  items, while the benchmark expects sales and other operating revenues, about
  `$193.4B`.

This gives the current reportable Kernel v3 headline: the general finance
agent path can reproduce the historical live10 best score (`8/10`) and also
hold `8/10` on a separate 10-item slice while preserving the full workflow
spine. The remaining work is not to add rules or answer tables; it is to make
the LLM/tool loop better at metric disambiguation and missing-source recovery.

### Extended holdout and failure-regression live testing

Additional live batches were run after the dev/test headline to expose broader
weaknesses and verify that fixes close real failures. These are debug and
regression slices, not promoted headline test sets. The benchmark reference
answers and gold annotations were still scoring-only material and were not
available to the agent loop.

Global holdout stress:

- Run: `run_global_finagent_holdout20_live_20260613`
- Dataset slice: `finagent_test_0_40.jsonl`, offset `20`, limit `20`
- Strict score: `9/20`
- Numeric accuracy: `0.4737`
- `citation_present_rate=1.0`
- `citation_preservation_rate=1.0`
- `claim_ledger_present_rate=1.0`
- `slot_frame_present_rate=1.0`
- `transform_plan_present_rate=1.0`
- `numeric_verifier_pass_rate=1.0`
- `synthesis_gate_pass_rate=1.0`
- `unsupported_numeric_claim_rate=0.0`
- `average_answer_numeric_support_rate=1.0`

Failure-regression batch:

- Run: `run_failure_regression_metric_nr_live_20260613`
- Scope: 11 real failures selected from FE and numerical-reasoning rows
- Strict score: `4/11`
- Closed failures: `FE_009` Goldman net revenues, `FE_031` Apple R&D,
  `FE_037` JPMorgan net interest income, and `NR_005` Meta net income growth
- Full trace spine remained present:
  `citation_present_rate=1.0`, `claim_ledger_present_rate=1.0`,
  `slot_frame_present_rate=1.0`, `transform_plan_present_rate=1.0`,
  `numeric_verifier_pass_rate=1.0`, `unsupported_numeric_claim_rate=0.0`

Second failure-regression batch:

- Run: `run_failure_regression_round2_live_20260613`
- Scope: the 7 remaining hard failures from the first regression batch
- Strict score: `1/7`
- Closed failure: `NR_004` NVIDIA gross margin
- Full trace spine again remained present:
  `citation_present_rate=1.0`, `claim_ledger_present_rate=1.0`,
  `slot_frame_present_rate=1.0`, `transform_plan_present_rate=1.0`,
  `numeric_verifier_pass_rate=1.0`, `unsupported_numeric_claim_rate=0.0`

The repaired rows demonstrate that the current work improved real capability
rather than tuning a fixed answer table. The host now exposes finance concepts,
labels, source provenance, target-binding reasons, fact-ledger context, and
formula traces to the LLM so the model can choose the requested metric and
answer shape. The host still validates citations, numeric support, units, and
trace contracts.

Remaining hard gaps after these batches:

1. `FE_020` and `FE_021`: total-revenue questions still need better line-item
   disambiguation across `sales and other operating revenues`, total revenues,
   total revenues plus other income, and generic SEC `Revenues`.
2. `FE_028`: adversarial or incorrect-premise questions need stronger LLM
   synthesis closure so the final answer says the premise is wrong instead of
   selecting a nearby line item.
3. `NR_001` and `NR_003`: net/operating margin questions still need more
   reliable acquisition of the correct revenue denominator.
4. `NR_007`: debt-to-equity now has formula intent support, but the live answer
   path still needs better alignment between liabilities/equity facts,
   calculator output, and final text.

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
