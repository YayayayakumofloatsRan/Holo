# Kernel v3 Finance Benchmark Track

This track turns the submitted Holo project proposal into a measurable implementation plan.
The goal is not to demonstrate a hand-picked chat transcript or optimize a finance-only
script. FAB-style tasks are treated as workflow pressure tests for Holo's general
intellectual workflow kernel: task framing, slot decomposition, source acquisition,
claim extraction, transform/calculation, verifier gates, synthesis gates, and failure
recovery.

## Objective

Holo should answer public-finance research questions through the normal Kernel v3 loop:

1. route the user question,
2. form a semantic task packet,
3. plan a next action,
4. validate and execute tools,
5. assess observations,
6. synthesize a cited answer,
7. record trace, evidence, cost, and failure diagnostics.

Benchmark gold answers are used only by the scoring layer after the run. They must not be
inserted into planner, evaluator, retrieval, memory, or synthesis prompts.

Each curated benchmark item should carry workflow annotations:

- `workflow_type`: the work shape being tested, such as `multi_entity_compute_compare`,
  `reconciliation`, `event_transaction`, `valuation_multiple`, `coverage_ratio`,
  `modeling_lite`, `regulatory_ratio`, or `disclosure_diff`.
- `required_slots`: the facts or assumptions that must be filled before a reliable answer.
- `evidence_policy`: required and forbidden source families, evidence terms, and authority
  expectations.
- `required_transforms`: calculations or reasoning transforms that should appear in the
  trace.
- `dealbreakers`: conditions such as citation required, calculator trace required,
  synthesis gate pass required, or assumptions labeled.
- `expected_trace`: trace records expected from a healthy workflow, such as
  `claim_ledger`, `slot_frame`, `transform_plan`, `verifier_gate`, and `synthesis_gate`.
- `failure_taxonomy`: labels used to classify failures before adding any new heuristic.

## Initial Benchmarks

- Finance Agent Benchmark: real financial research tasks with Google Search and SEC EDGAR
  style tool assumptions.
- Finance Agent v2 public set: public development questions from Vals'
  Finance Agent v2 benchmark, focused on analyst-style filing research,
  transaction analysis, DCF/LBO modeling, and numeric convention handling.
- FinAgent Benchmark: SEC 10-K/10-Q grounded questions with gold answers, numeric values,
  tolerance, evidence excerpts, and required tool annotations.
- SECQUE: SEC filing long-context questions with filing metadata and judge-oriented answer
  references.
- FinanceQA and FinQA: filing-context and numerical-reasoning suites for concept, assumption,
  and calculation coverage.

The local historical 40-item file is useful for fast iteration, but it is not enough for a
defensible project report unless it is paired with a provenance manifest. Public benchmark
imports are now the preferred path for reported scores.

## Public Dataset Import

Normalize a local CSV/JSON/JSONL export from a public benchmark into the Kernel v3 benchmark
schema:

```bash
./holo-v3 bench finance-import \
  --benchmark finance_agent_benchmark \
  --input data/raw/finance_agent_benchmark.csv \
  --output .state/kernel_v3/bench/finance/finance_agent_benchmark.normalized.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/finance_agent_benchmark.manifest.json
```

Supported import formats:

- `finance_agent_benchmark`: HuggingFace-style fields such as `Question`, `Answer`,
  `Question Type`, `Expert time (mins)`, and `Rubric`.
- `finance_agent_v2_public`: plain text public development questions, one question
  per line, with no public gold answer in the normalized prompt item.
- `financebench`: PatronusAI FinanceBench-style rows with `financebench_id`,
  `company`, `doc_name`, `question_type`, `question_reasoning`, `question`,
  `answer`, `justification`, `evidence`, `gics_sector`, `doc_type`,
  `doc_period`, and `doc_link`. It supports `--mode oracle_evidence`,
  `--mode doc_retrieval`, and `--mode question_only` so reports can separate
  evidence-conditioned answering, document acquisition, and bare-question
  generalization.
- `secque`: question, answer/ground truth, SEC filing context/supporting data, accession,
  page/item/section metadata.
- `financeqa`: question, answer, filing context, question type, company, file link/name.
- `finqa`: report text/table context, answer, and numerical-reasoning annotations.
  It supports `--mode oracle_context` for numerical reasoning with supplied
  report/table context and `--mode question_only` for acquisition/generalization
  ablations.

Import policy:

- gold answers are scoring-only and are never inserted into the agent prompt;
- rubrics and reference chain-of-thought/program annotations are scoring-only;
- benchmark-provided filing/report context may be inserted into the prompt as evidence;
- every import can write a manifest with source URL, prompt policy, item count, and warnings.

If the local raw file is missing, fetch known small public benchmark files first.
`finance-fetch` supports built-in direct URLs for FAB v2 public, FinanceBench
merged open-source rows, and FinQA `train`/`dev`/`test`/`private_test` JSON files;
it also accepts `--url` for a local mirror. With `--normalized-output`, fetch and
import happen in one step:

```bash
./holo-v3 bench finance-fetch \
  --benchmark financebench \
  --output data/raw/financebench.jsonl \
  --normalized-output .state/kernel_v3/bench/finance/financebench_oracle.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/financebench_oracle.manifest.json \
  --annotation-output .state/kernel_v3/bench/finance/financebench_oracle.gold.jsonl \
  --mode oracle_evidence

./holo-v3 bench finance-fetch \
  --benchmark finqa \
  --split test \
  --output data/raw/finqa_test.json \
  --normalized-output .state/kernel_v3/bench/finance/finqa_test_oracle_context.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/finqa_test_oracle_context.manifest.json \
  --annotation-output .state/kernel_v3/bench/finance/finqa_test_oracle_context.gold.jsonl \
  --mode oracle_context
```

Keep downloaded raw files under `data/raw` or another explicit cache path. Do
not repeatedly download these sources during benchmark iteration.

2026-06-11 fetch/import smoke:

- FinanceBench built-in fetch downloaded `958,087` bytes from the PatronusAI
  merged JSONL export, normalized `5` `oracle_evidence` rows, skipped `0`, and
  wrote a matching scoring annotation sidecar.
- FinQA built-in fetch downloaded `10,954,658` bytes from the public `dev` JSON,
  normalized `5` `oracle_context` rows, skipped `0`, and wrote a matching
  scoring annotation sidecar.
- These smoke runs validate the public gold-backed data path only. They are not
  live agent accuracy scores.
- FinQA annotations now use the generic `numeric_reasoning` workflow shape:
  `question_context`, `input_values`, `formula_or_operation`, and `answer_unit`
  slots; `calculator.compute`, verifier, and synthesis-gate traces; and a
  provided-report-context evidence policy. The reference program remains
  scoring-only and is not prompt context.
- Follow-up runtime smoke confirms the oracle-context finalization path.
  FinanceBench `oracle_evidence` is now promoted to citable retrieval evidence
  before finalization, so it no longer dies as a `max_network_fetches` or
  retrieval-template failure when the benchmark has already supplied the source
  excerpt. The first FinanceBench oracle item
  (`run_financebench_oracle_smoke1_after_fallback_synthesis_gate`) passes in a
  no-network fake-processor smoke with numeric accuracy `1.0`, citation
  preservation `1.0`, answer numeric support `1.0`, and
  claim/slot/transform/verifier/synthesis-gate presence `1.0`; the gold answer
  is still scoring-only and is not prompt context.
  FinQA `oracle_context` now uses the same provided-context evidence path plus a
  table-average calculator preflight. The first smoke item
  (`run_finqa_oracle_smoke1_after_table_average_synthesis_gate`) passes with
  one `calculator.compute` trace, one formula trace, verifier-gate pass,
  synthesis-gate pass, citation preservation `1.0`, and annotation overall /
  workflow / substrate / numeric scores of `1.0`. This is a single-item
  no-network smoke for the oracle-context path, not a broad FinQA subset score.
- A first FinQA oracle-context subset diagnostic then ran `20` local `dev` rows
  without network access or benchmark gold in prompts
  (`run_finqa_oracle20_confirm_formula_patterns_v1`). Generic table/text
  arithmetic preflight now covers table averages, indexed cumulative return,
  percentage-of-total, period change, simple projection, and pretax/after-tax
  difference patterns. On this subset, pass rate and numeric accuracy are
  `0.30`, calculator-used and formula-trace rates are `0.60`, substrate score is
  `0.925`, workflow score is `0.96`, citation preservation is `0.95`,
  synthesis-gate pass is `1.0`, and unsupported numeric claim rate is `0.0`.
  The remaining misses are formula-binding / target-cell-selection gaps; do not
  report this as an official FinQA score.
- Full public gold-backed baseline runs have now started. See
  `docs/KERNEL_V3_PUBLIC_BENCHMARK_BASELINES_2026-06-11.md` for the compact
  table. FinanceBench-150 `oracle_evidence` no-network/fake-processor baseline
  (`run_financebench_150_oracle_evidence_fake_v1`) produced pass rate `0.20`,
  numeric accuracy `0.2381`, workflow score `0.9132`, substrate score `1.0`,
  citation preservation `0.8733`, and unsupported numeric claim rate `0.1067`.
  This proves the public FinanceBench oracle-evidence path reaches the generic
  claim/slot/transform/verifier/synthesis spine, while exposing numeric target
  selection and calculator-binding gaps.
- FinanceBench `doc_retrieval` has been split into a negative-control result
  and a true live probe. The full 150-row fake/no-network run
  (`run_financebench_150_doc_retrieval_fake_v1`) is not a capability score; it
  verifies that Holo does not fabricate support when only document metadata is
  present and evidence acquisition is unavailable. A small live 3-item probe
  (`run_financebench_doc_retrieval_live_limit3_v1`) did perform retrieval
  (`1.3333` average retrieval runs, `8` to `16` fetches per item), but still
  scored `0/3` because no citable finance facts, citations, or calculator inputs
  were extracted. The next doc-retrieval work should therefore target source
  acquisition and document-to-fact extraction, not more fixed answer heuristics.
- Follow-up Retrieval Workbench live1 probes then produced citable facts/claims
  for the first FinanceBench doc-retrieval item, but selected the wrong numeric
  support: secondary/current StockAnalysis capex (`899M`) rather than the target
  FY2018 10-K cash-flow statement capex row (`1577M`). Issue #3 P0 adds
  target-document binding and primary-source numeric binding so model-guided
  evidence workbench decisions can be checked against the target document,
  period, statement/table, and line item before final numeric support is
  accepted.
- Issue #3 live1 is now closed by `run_financebench_doc_live1_binding_v7`:
  pass rate / numeric accuracy `1.0` on the first doc-retrieval item,
  `retrieval_runs=1`, `facts=114`, `claims=114`, claim ledger / slot frame /
  transform plan / verifier gate / synthesis gate present and passed, citation
  preservation `1.0`, unsupported numeric claim rate `0`, and answer numeric
  support `100%`. The small follow-up
  `run_financebench_doc_live3_binding_v1` was `1/3`; all three items reached
  the generic workflow substrate, but items 2-3 failed at unsupported numeric
  synthesis / missing line-item support. `run_financebench_doc_live3_binding_v2`
  is now `2/3`: item 2 passes after fixing inline `Document period` parsing for
  `Assume ...` prompts and binding balance-sheet net PP&E / net PPNE to SEC
  `PropertyPlantAndEquipmentNet`. The v2 summary reports pass rate / numeric
  accuracy `0.6667`, claim-ledger / slot-frame / transform-plan present rate
  `1.0`, citation preservation `0.6667`, synthesis-gate pass rate `0.6667`,
  and unsupported numeric claim rate `0.3333`. Item 3 remains a capital-
  intensity slot/transform gap, not the original secondary-current `899M`
  failure.
- Task Compiler v1 adds the missing intermediate program layer for this gap:
  finance runtime now journals a `compiled_task_program` with generic
  `TaskSpec`, `EvidenceSpec`, and `TransformSpec` records. The live validation
  `run_financebench_doc_live3_task_compiler_v1` keeps the slice at `2/3`, but
  compiled-program presence is `1.0` and item 3 is no longer just a failed
  retrieval/synthesis item. It is compiled as a `compute` task with five
  evidence specs, three capital-intensity transform specs, and missing slots
  for capital expenditures, operating cash flow, net PP&E, and assets. The
  current final answer still fails numeric support, so the correct next work is
  slot filling plus calculator binding, not another threshold search patch.
- Target-slot binding closes the first FinanceBench doc-retrieval slice.
  `run_financebench_doc_live3_target_slots_v4` passes `3/3`: pass rate /
  numeric accuracy `1.0`, workflow / substrate score `1.0`, citation
  preservation `1.0`, numeric verifier / verifier gate / synthesis gate pass
  rate `1.0`, unsupported numeric claim rate `0`, and calculator/formula trace
  rate `0.3333`. The third item now keeps FY2022 SEC companyfacts evidence for
  revenue, operating cash flow, capex, net PP&E, and assets, then computes
  capital intensity with a host calculator trace. The first broader
  `run_financebench_doc_live10_target_slots_v1` baseline is `3/10`: the closed
  slice holds, while later rows expose target PDF/table extraction,
  source-resolution, and qualitative disclosure-answer gaps.
- A true model/network revalidation,
  `run_financebench_doc_live3_model_net_v1`, keeps the closed live3 slice at
  `3/3` with citation preservation `1.0`, unsupported numeric claim rate `0`,
  and average retrieval runs `1.3333`. The fourth-row probe then isolates the
  next gap. `run_financebench_doc_item4_model_net_v6` clears the
  `investors.3m.com` source miss and reaches behavior/workflow/substrate score
  `1.0`, but still fails answer scoring because qualitative MD&A driver
  synthesis is not yet reliable. `run_financebench_doc_item4_model_net_v7`
  exposed a benchmark-scorer false positive: bare `3M` was interpreted as
  `3,000,000` and a failure report could pass despite failed
  citation/verifier/synthesis gates. The scorer and FinanceBench annotation
  export now reject that pattern, and v7 re-scores as failed; treat it as a
  diagnostic, not as a quality pass.
- 2026-06-12 later item4 follow-ups moved the boundary from retry mechanics to
  target-document source identity. `v20` is the corrected negative control:
  after host source-contract tightening, generic `data.sec.gov` companyfacts no
  longer satisfy FinanceBench `doc_retrieval`, so the row fails instead of
  falsely passing. `v21` and `v22` then pass the same fourth row
  (`financebench_id_01226`) with target SEC archive filing evidence, citation
  preservation `1.0`, claim-ledger / slot-frame / transform-plan presence `1.0`,
  verifier and synthesis gates passed, and source hosts including `www.sec.gov`.
  The benchmark annotation scorer now preserves required source URLs and treats
  same-accession SEC archive documents as equivalent target filings while still
  rejecting generic companyfacts. The open issue is cost, not this row's source
  grounding: v21/v22 consumed roughly `382k`/`523k` model tokens, so the next
  iteration must shrink Workbench/planner context.
- A no-model rescore of v22 after this source-equivalence cleanup
  (`run_financebench_doc_item4_model_net_v22_rescore`) reaches dev annotation
  overall `1.0`, required source hit `4/4`, required source URL hit `1/1`,
  numeric score `1.0`, workflow/substrate score `1.0`, and pass rate `1.0`.
- Retrieval payloads now include a compact `compiled_task_hint` built from the
  target question and document binding before acquisition. It exposes
  TaskSpec/EvidenceSpec/TransformSpec to the LLM Workbench so the model can
  judge missing slots and next document targets from an explicit work program
  rather than from raw snippets alone. The hint is advisory work context, not
  evidence, and still requires host-validated citations/facts/transforms before
  synthesis.
- Retrieval Workbench packets now use task-aware compact selection. The
  selection score combines the compiled evidence/transform specs, target
  document contract, required statement/line item, and table-like signals, so
  late target-filing candidates are preserved while low-value noise is dropped
  before the LLM call.
- Workbench document summaries now carry bounded reader diagnostics and
  task-ranked table-like snippets. For filing/PDF-heavy rows this gives the LLM
  the missing intermediate state: parser/text mode, extracted character/page
  diagnostics, table-like block counts, readable preview text, and candidate
  row-like numeric excerpts selected against the compiled task. The rows are not
  treated as facts until the host can bind them to evidence/citations or
  formula traces.
- Regression check after this packet change: the workbench/finance/document
  expansion suite completed with `205 passed`, and
  `run_stable4_event_resolver_v1_rescore_after_reader_packet` preserved
  stable4 answer/citation presence, claim-ledger, slot-frame, transform-plan,
  calculator/formula-trace, verifier-gate, and unsupported numeric rates at
  `1.0`/`0.0` as applicable.
- FinQA `dev` oracle-context `100` no-network/fake-processor baseline
  (`run_finqa_dev_oracle100_fake_v1`) produced pass rate / numeric accuracy
  `0.15`, workflow score `0.925`, substrate score `0.8816`,
  calculator/formula-trace rate `0.37`, citation preservation `0.92`, and
  unsupported numeric claim rate `0.06`. This confirms the larger FinQA gap is
  formula/target binding rather than citation preservation.

Finance Agent v2 public import:

```bash
./holo-v3 bench finance-import \
  --benchmark finance_agent_v2_public \
  --input data/raw/fabv2_public.txt \
  --output .state/kernel_v3/bench/finance/fabv2_public_dev.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/fabv2_public_dev.manifest.json
```

FinanceBench import modes:

```bash
./holo-v3 bench finance-import \
  --benchmark financebench \
  --mode oracle_evidence \
  --input data/raw/financebench.jsonl \
  --output .state/kernel_v3/bench/finance/financebench_oracle.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/financebench_oracle.manifest.json \
  --annotation-output .state/kernel_v3/bench/finance/financebench_oracle.gold.jsonl

./holo-v3 bench finance-import \
  --benchmark financebench \
  --mode doc_retrieval \
  --input data/raw/financebench.jsonl \
  --output .state/kernel_v3/bench/finance/financebench_doc_retrieval.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/financebench_doc_retrieval.manifest.json \
  --annotation-output .state/kernel_v3/bench/finance/financebench_doc_retrieval.gold.jsonl
```

In `oracle_evidence`, the provided evidence excerpt is prompt context but the
reference answer and justification stay scoring-only. In `doc_retrieval`, only
document metadata/link is prompt context; the evidence excerpt is retained for
audit/scoring but not prompted. In `question_only`, neither evidence nor document
hints are prompted.

`--annotation-output` exports the post-run `--dev-gold` sidecar directly from
the normalized dataset. It carries workflow type, slots, evidence policy,
required transforms, dealbreakers, expected trace records, failure taxonomy,
source requirements, and numeric expectations extracted from reference answers.
This sidecar is scoring material only and must never enter model prompts.

The official public file lives at
`https://raw.githubusercontent.com/vals-ai/finance-agent-v2/main/data/public.txt`.
Keep it as a local input for reproducible runs and to avoid accidental repeated downloads.
The current repository snapshot includes the downloaded public file at
`data/raw/fabv2_public.txt` and its normalized import at
`data/bench/finance/fabv2_public.jsonl` with `27` public questions. The public set has
no public gold, so report behavior, substrate, workflow, cost, and failure-taxonomy
metrics rather than official accuracy.

## CLI

Run Holo against a JSONL benchmark:

```bash
HOLO_V3_LIVE_MODEL=1 ./holo-v3 bench finance \
  --dataset .state/kernel_v3/bench/finance/finance_agent_benchmark_public.normalized.jsonl \
  --limit 10 \
  --online \
  --execution-profile finance-fact-fast \
  --research-profile finance_fundamentals \
  --live-retrieval \
  --live-search-strategy adaptive
```

Execution profiles:

- `finance-fact-fast`: default benchmark lane. Skips resident mission
  supervision and workmethod framing; uses a compact context, model planner,
  rule evaluator, model synthesizer, and small retrieval/loop budgets.
- `finance-modeling`: medium lane for multi-metric finance analysis and
  calculations.
- `web-research`: open-web lane for market analysis questions that need broader
  source families.
- `long-mission`: full resident mission loop. Use for stress-testing the
  always-on architecture, not for simple benchmark fact extraction.

Finance execution substrate:

- `FinanceFactLedger` converts retrieval evidence into structured facts with
  metric, period, value, unit, evidence ref, and citation ref.
- `FinanceFormulaPlanner` compiles common analyst calculations from fact-ledger
  inputs into `calculator.compute` payloads. The first supported templates are
  CAGR, DIO, margin, basis-point difference, EV/Revenue, YoY growth, and bridge
  subtotal. If required facts are absent, it journals missing-fact diagnostics
  instead of guessing.
- `calculator.compute` is a host-validated Decimal calculator. It accepts a
  formula expression, variables, optional unit, and input fact ids, then journals
  a `FormulaTrace`.
- `finance.verify_numeric` is a deterministic final gate for finance profiles
  that require numeric verification. It checks material answer numbers against
  fact ledger entries or formula traces and blocks unsupported finance numbers
  before final answer delivery.

Curated FAB v2 development slice:

```bash
./holo-v3 bench finance \
  --dataset data/bench/finance/fabv2_dev10.jsonl \
  --dev-gold data/bench/finance/fabv2_dev10.gold.jsonl \
  --limit 10 \
  --execution-profile finance-fact-fast \
  --mission off \
  --online \
  --research-profile finance_fundamentals \
  --live-retrieval
```

The curated dev10 slice is a development harness, not a replacement for the
official Vals split. The gold annotation file is used only after a run to score
behavior, numeric expectations, and substrate usage. It must not be placed into
`--question-prefix`, prompt context, memory, or any runtime context sent to a
model.

`data/bench/finance/fabv2_dev10.jsonl` and
`data/bench/finance/fabv2_dev10.gold.jsonl` now include workflow annotations:
workflow type, required slots, evidence policy, required transforms, dealbreakers,
expected trace records, and failure taxonomy. A replay score against existing live
outputs therefore reports both traditional behavior/substrate scores and a workflow
score. This is intentionally stricter than answer-only scoring.

The repository also includes
`data/bench/finance/holo_finance_workflow_challenge.jsonl`, a workflow-oriented
challenge set with `50` items. It is not a gold-answer benchmark; it is a pressure
suite for compute/compare, reconciliation, event transactions, valuation multiples,
coverage ratios, earnings reconciliation, disclosure diff, market-event analysis,
modeling-lite, and regulatory-ratio workflows. Each item carries workflow slots,
source policy, required transforms, dealbreakers, expected trace records, and
failure taxonomy labels; it does not carry answer gold.

Score existing predictions without running Holo:

```bash
./holo-v3 bench finance \
  --dataset data/finagent.jsonl \
  --predictions artifacts/finance_predictions.jsonl \
  --output artifacts/finance_bench_results.jsonl \
  --summary-output artifacts/finance_bench_summary.json
```

Render benchmark artifacts for review:

```bash
./holo-v3 bench finance-report \
  --results artifacts/finance_bench_results.jsonl \
  --output artifacts/finance_bench_report.md

./holo-v3 bench finance-graph \
  --results artifacts/finance_bench_results.jsonl \
  --format dot \
  --output artifacts/finance_bench.dot
```

## Result Schema

Each item result records:

- benchmark id and question,
- Holo answer,
- task id, run id, thread id,
- scorecard,
- trace metrics,
- trace refs,
- failure report if any.

The summary reports:

- pass rate over scored items,
- answer-present rate,
- citation-present rate,
- numeric accuracy,
- calculator-used rate,
- numeric-verifier pass rate,
- formula-trace present rate,
- finance fact count,
- answer numeric support rate,
- finance numeric failure taxonomy,
- optional dev annotation behavior/numeric/substrate score,
- adversarial/unavailable-answer accuracy,
- average token use,
- average processor duration,
- average retrieval runs,
- average query repetition rate,
- claim-ledger, slot-frame, transform-plan, verifier-gate, and synthesis-gate coverage,
- unsupported numeric claim rate,
- missing-slot recovery rate,
- cost per passed task,
- repeatability score when duplicate item runs are present,
- workflow type distribution and optional workflow annotation scores.

The report renderer turns item results into Markdown, HTML, or JSON with:

- score and efficiency summary,
- status, failure-mode, and score-reason breakdowns,
- weakest items ranked by score, citations, trace cost, repetition, and answer length,
- workflow and substrate metrics including repeatability, synthesis-gate status,
  verifier-gate status, and unsupported numeric claim rate,
- recommended next experiments.

## Next Steps

## Live Smoke Notes

2026-06-10 KHC adjusted EBITDA bridge follow-up:

- implemented bridge source grouping in `FinanceFormulaPlanner`, keyed by
  citation/evidence/source, before formula binding;
- bridge subtotals now preserve retrieval extraction order and select one
  reconciliation-table column instead of adding adjacent annual columns
  together;
- the fact ledger now preserves direct `Adjusted EBITDA $ ...` rows even when
  a following table title mentions EPS/per-share terms;
- regression coverage now includes a mixed 10-Q/10-K bridge fixture that must
  choose the 10-K group, keep the selected column together, and compute the
  reported adjusted EBITDA subtotal through `calculator.compute`;
- related local regression command:

```bash
.venv/bin/python -m pytest -q \
  tests/test_kernel_v3_finance_engine.py \
  tests/test_kernel_v3_finance_benchmark.py \
  tests/test_kernel_v3_retrieval_document_expansion.py \
  tests/test_kernel_v3_phase98_sec_edgar_provider.py \
  tests/test_kernel_v3_phase99_source_query_provider.py
```

Result: `140 passed`.

Live KHC smoke command:

```bash
HOLO_V3_LIVE_MODEL=1 .venv/bin/python -m kernel_v3.cli bench finance \
  --dataset data/bench/finance/fabv2_dev10.jsonl \
  --dev-gold data/bench/finance/fabv2_dev10.gold.jsonl \
  --offset 1 --limit 1 \
  --output .state/kernel_v3/bench/finance/run_khc_after_bridge_column_fix.jsonl \
  --summary-output .state/kernel_v3/bench/finance/run_khc_after_bridge_column_fix.summary.json \
  --thread-prefix fabv2-khc-after-bridge-column-fix \
  --execution-profile finance-fact-fast \
  --mission off --online \
  --planner model --evaluator fake --synthesizer model \
  --semantic-intake fake --turn-router fake \
  --research-profile finance_fundamentals --research-depth light \
  --context-profile compact --live-retrieval --live-search-strategy adaptive \
  --max-output-tokens 1200
```

Observed live status:

- retrieval runs: 1
- calculator calls: 1
- formula traces: 1
- finance facts: 86
- query repetition: 0%
- dev annotation substrate score: 1.0
- numeric verifier status: failed
- answer numeric support: 64%
- failure taxonomy: `unsupported_answer_number`

Interpretation: acquisition and deterministic substrate are now active on KHC,
but the final answer path still needs repair/calibration so synthesis does not
emit display numbers that the fact ledger or formula traces cannot support.

2026-06-10 live smoke and repeat smoke on `fabv2-hd-low-dio` with `finance-fact-fast`,
mission disabled, live retrieval, model planner, fake evaluator, and model
synthesizer:

- retrieval runs: 1
- processor calls: 3
- total tokens: about 78k
- processor duration: 46,941 ms on the repeat cached run; the first uncached
  successful run took 198,351 ms
- fetched SEC companyfacts sources: HD and LOW
- finance facts: 36
- calculator calls: 4
- formula traces: 4
- numeric verifier: passed
- answer numeric support rate: 100%
- dev annotation behavior/numeric/substrate/overall score after post-run
  scoring: 1.0 / 1.0 / 1.0 / 1.0

This confirms the deterministic finance substrate can close a real FAB v2 style
DIO task with SEC facts, host calculator traces, and numeric verification. It
does not yet prove the full curated dev10. The remaining engineering pressure is
cost and breadth: token use and wall time are still too high, and bridge,
transaction multiple, DCF/LBO, MLR, and purchase-price-allocation cases still
need live calibration.

Small-batch live calibration on the first three curated items showed the next
weak spots:

- `fabv2-hd-low-dio`: stable after adding Chinese hundred-million display
  support in the numeric verifier. Repeat run: verifier passed, 100% numeric
  support, overall dev annotation score 1.0.
- `fabv2-khc-adjusted-ebitda-bridge`: retrieval found KHC SEC companyfacts, but
  companyfacts alone did not expose non-GAAP adjusted EBITDA bridge components;
  calculator did not run because the fact ledger lacked add-back inputs.
- `fabv2-pfe-sgen-transaction-multiple`: retrieval over companyfacts did not
  acquire transaction-specific facts such as deal value and target revenue from
  8-K / merger / acquisition-note sources; numeric verifier correctly blocked
  unsupported answer numbers.

After the first transaction failures, the acquisition layer was strengthened so
transaction/bridge tasks prioritize SEC submissions metadata, expand primary
filing links before generic search pages, diversify event filings across years,
and recurse once through SEC `filings.files` archive chunks. Local regressions
cover all of these behaviors, including older-event 8-K discovery from an
archive submissions file.

Live PFE/SGEN smoke after those changes still did not close:

- `smoke07`: answer present with SEC citations, but `finance_fact_count=0`,
  `calculator_call_count=0`, `formula_trace_count=0`, 3 retrieval runs,
  136k tokens, 32 fetches. The agent cited unrelated Pfizer 2025 8-K filings.
- `smoke08`: same failure shape after source-order fixes, 134k tokens,
  32 fetches.
- `smoke09`: fetches dropped to 24 and tokens to 106k after archive expansion,
  but evidence/citations/facts were still zero and the run stopped at the fast
  tool-call cap. The final failure was evidence coverage, not a permission or
  live-retrieval configuration issue.
- `smoke10`: after reserving fetch budget for second-depth archive expansion,
  the run acquired Seagen companyfacts and produced 12 finance facts with
  numeric verification passing, but it still missed the Pfizer transaction
  value, so `calculator.compute` did not run.
- `smoke12`: after raising SEC `recent` scan depth and avoiding the accidental
  `target revenue` -> `TGT` issuer match, the run still fetched unrelated
  Pfizer 2021/2022 8-K documents and produced `finance_fact_count=0`. This
  confirms that the remaining gap is event/accession resolution, not only
  generic ranking or budget.
- `smoke15` through `smoke17`: the transaction path now selects multi-issuer
  source-directory entries, records failed issuer event pages as
  `find_alternate_event_source`, and ranks the Pfizer March 2023 merger 8-K
  (`0001193125-23-068538`) ahead of unrelated earnings/cost-action 8-Ks. The
  numeric verifier no longer treats SEC Item codes such as `7.01` and `8.01`
  as unsupported answer numbers. A direct live SEC extractor check now places
  the `$229.00 in cash` consideration span inside a tight
  `max_spans_per_document=4` budget, and the fact ledger can classify that span
  as `purchase price`. The full PFE/SGEN benchmark run still does not close:
  it satisfies required source families but does not yet produce the needed
  `calculator.compute` trace because the accepted evidence-to-ledger handoff
  still misses enough transaction value / target revenue facts for EV/Revenue.
- `smoke18` direct SEC extraction check: the extractor now treats SEC complete
  submission text as a large filing bundle even when it is detected as HTML, so
  exhibit content beyond the old 200k-character prefix can be searched. A live
  check against Pfizer's official `0001193125-23-068538.txt` filing produced
  top spans containing both `$229 per Seagen share` and `total enterprise value
  of approximately $43 billion`; the finance ledger projected those spans into
  `transaction value=43000000000`, `purchase price=229`, and revenue facts while
  filtering non-facts such as SEC item numbers, exhibit IDs, dates, and call
  times. This validates the document-to-ledger substrate on the real filing, but
  the full PFE/SGEN benchmark loop still needs a fresh end-to-end run before it
  can be marked solved.
- `smoke19` full-loop PFE/SGEN rerun: after fixing per-share binding and SEC
  document-identifier noise in the numeric verifier, the full benchmark loop
  acquired the official SEC 8-K / Exhibit 99.1 evidence, projected 17 finance
  facts, ran one `calculator.compute` formula trace, and passed
  `finance.verify_numeric` with 100% answer numeric support. Post-run dev
  annotation scored behavior/substrate/overall as 1.0 / 1.0 / 1.0 for this
  item. This is the first transaction-multiple item where the retrieval,
  ledger, calculator, and verifier substrate closed end to end without using
  gold answers in prompts.

Curated dev10 live run after `smoke19`:

- command profile: `finance-fact-fast`, mission off, live retrieval, model
  planner, fake evaluator, model synthesizer, parallel 2;
- overall dev annotation score: 0.8111;
- behavior score: 0.8667;
- substrate score: 0.5667;
- calculator-used rate: 0.20;
- formula-trace present rate: 0.20;
- numeric-verifier pass rate: 0.50;
- average answer numeric support rate: 70.56%;
- average retrieval runs: 1.1;
- average token use: 62,482.3;
- strongest items: `fabv2-hd-low-dio` and
  `fabv2-pfe-sgen-transaction-multiple`, both with behavior/substrate score
  1.0 and passing numeric verification;
- main failure modes: `required_trace_missing` on 8/10 items,
  `expected_answer_content_missing` on 4/10 items, and one required-source miss
  on the CRM DCF task.

The current bottleneck is no longer only source acquisition. The strongest
evidence is that DIO and transaction-multiple questions close with calculator
traces, while bridge, DCF/LBO, fixed-charge coverage, EV/EBITDA, MLR, and
purchase-price-allocation questions often gather evidence but do not compile a
host formula or run numeric verification. The next improvement should expand
`FinanceFormulaPlanner` and the fact ledger for those task families, and add an
LLM-assisted fact/noise reviewer as an advisory layer without weakening the
host deterministic numeric gate.

Post-dev10 EV/EBITDA iteration:

- `FinanceFormulaPlanner` now recognizes `EV/EBITDA` / enterprise-value-to-
  EBITDA intent, can bind direct EBITDA facts, or derive EBITDA from net income,
  interest expense, tax expense, and depreciation/amortization when all inputs
  are available.
- `FinanceFactLedger` now extracts market-data-page style facts such as market
  cap, enterprise value, total debt, total cash, and EBITDA from natural text.
  This makes secondary market-data sources usable as formula inputs instead of
  leaving them as unstructured answer context.
- Multi-entity preflight now supports `ev_ebitda` in addition to DIO, so
  comparison tasks can emit per-company formula traces instead of a single
  collapsed formula.
- Missing-fact fallback now covers `ev_ebitda`; when enterprise value / market
  cap, debt, cash, EBITDA, or EBITDA components are absent, the host can compile
  a targeted `retrieval.run` action for those missing facts even if the model
  planner fails JSON repair.
- A targeted live rerun of `fabv2-lulu-vsco-ev-ebitda` confirmed the new
  formula intent is active: journaled `finance_formula_plan` records changed
  from `not_applicable` to `missing_facts` with explicit missing inputs
  (`enterprise_value_or_market_cap`, `debt`, `cash`,
  `ebitda_or_ebitda_components`). The item still did not pass because the
  acquired SEC evidence lacked market-value and EBITDA inputs, but the failure
  is now actionable at the retrieval/fact-acquisition layer rather than hidden
  as an unsupported formula.
- Local substrate replay with market-page style text now produces a complete
  EV/EBITDA formula trace from market cap, debt, cash, and EBITDA. The remaining
  live gap is acquiring those market-data facts reliably in the benchmark loop.
- Source-directory acquisition for EV/EBITDA missing facts now includes Yahoo
  Finance key-statistics pages and boosts market-data providers for valuation,
  market cap, enterprise value, debt, cash, EBITDA, and EV/EBITDA queries. A
  source-query replay for `LULU EV/EBITDA market cap enterprise value debt cash
  EBITDA` ranks `https://finance.yahoo.com/quote/LULU/key-statistics/` first,
  followed by quote/market-data pages. This improves candidate acquisition, but
  live parsing of market-data pages still needs benchmark validation.

2026-06-10 handoff status:

- GPT 5.5 Pro's requested finance substrate is implemented at v1 scope:
  `calculator.compute`, `FinanceFactLedger`, `FinanceFormulaPlanner`,
  deterministic `finance.verify_numeric`, FAB v2 public/dev10 import and
  annotation scoring, substrate trace metrics, verifier failure taxonomy, and
  fast-lane hard budgets are all present in the code path.
- The substrate is now partially generalized out of the finance domain pack.
  Kernel v3 has domain-neutral contracts for `Claim`, `SlotFrame`,
  `EvidencePolicy`, `TransformPlan`, and `VerificationGateResult`. Finance
  currently acts as the first adapter: `FinanceFact` projects into `Claim`,
  finance formula plans project into generic `TransformPlan`, finance task
  requirements project into `SlotFrame`, and `finance.verify_numeric` projects
  into `VerificationGateResult`. Runtime traces now journal `claim_ledger`,
  `slot_frame`, `transform_plan`, and `verifier_gate_result` alongside the
  existing finance-specific records.
- Benchmark metrics and reports now expose the generic substrate as well as
  finance-specific counters: claim count, slot-frame presence, missing slots,
  transform-plan presence/count, ready versus missing-slot transform-plan
  counts, verifier-gate status/pass/fail state, and verifier-gate issue count.
  `FinanceBenchmarkSummary` also reports claim-ledger present rate,
  slot-frame present rate, average missing slots, transform-plan present rate,
  average transform plans, and verifier-gate pass rate. This lets future domain
  packs reuse the same scoring and visualization spine instead of adding
  isolated benchmark-only metrics.
- Cost control is not finished. The `finance-fact-fast` lane has hard
  step/tool caps and provider-call budget enforcement, but its token budget is
  currently relaxed for reliability while ledger extraction, formula binding,
  and synthesis repair stabilize. In reports, describe this as a bounded fast
  execution lane with a temporarily broad token envelope, not as a fully
  optimized low-token lane.
- The current real-task capability is measurable but not yet reliable enough to
  claim Finance Agent v2 competence. Representative live successes now include
  `fabv2-hd-low-dio`, `fabv2-khc-adjusted-ebitda-bridge`,
  `fabv2-pfe-sgen-transaction-multiple`, and
  `fabv2-wsc-adjusted-ebitda-addback-trend`: each has closed at least once with
  retrieval evidence, structured finance facts, calculator/formula traces, and
  numeric verification.
- The latest KHC adjusted-EBITDA bridge smoke closes through the reliability
  gate after a scale repair. Earlier KHC runs exposed two bad behaviors:
  bridge formulas could mix unrelated evidence groups, and a reported
  `Adjusted EBITDA $ 6,003` from a table marked `in millions` could be traced
  as `6003 USD`. The formula planner now rejects component subtotals that do
  not match the reported adjusted subtotal, falls back to a conservative
  `reported_adjusted` calculator trace, and infers table scale from related
  facts in the same reconciliation group. The live rerun
  `run_khc_after_reported_adjusted_scale_fix_live` produced
  `retrieval_runs=1`, `fetches=8`, `finance_fact_count=218`,
  `calculator_call_count=1`, `formula_trace_count=1`,
  `numeric_verifier_status=passed`, `answer_numeric_support_rate=100%`,
  `citation_present_rate=100%`, and post-run dev annotation `overall_score=1.0`.
  The final user-visible answer was a host fallback because the model
  synthesizer still inserted unsupported bridge numbers; that is now a
  synthesis/answer-repair quality issue rather than a missing substrate issue.
- 2026-06-10 stable3 rerun status after adding generic substrate metrics:
  `fabv2-khc-adjusted-ebitda-bridge` and
  `fabv2-wsc-adjusted-ebitda-addback-trend` are currently repeatable positive
  substrate examples. A later `run_stable3_after_rescue` live batch produced
  `overall_score=0.8651`, behavior score `0.9524`, substrate score `0.7778`,
  average retrieval runs `1.0`, calculator-used rate `0.6667`, claim-ledger
  present rate `0.6667`, and verifier-gate pass rate `1.0` on items that
  reached verification. KHC in that batch produced `retrieval_runs=1`,
  `calculator_call_count=1`, `formula_trace_count=1`,
  `finance_fact_count=156`, `claim_count=156`, `slot_frame_present=true`,
  `transform_plan_count=2`, `numeric_verifier_status=passed`,
  `verifier_gate_status=passed`, and 100% answer numeric support. WSC in the
  same batch produced `retrieval_runs=1`, `calculator_call_count=1`,
  `formula_trace_count=1`, `finance_fact_count=186`, `claim_count=186`,
  `slot_frame_present=true`, `transform_plan_count=1`,
  `numeric_verifier_status=passed`, `verifier_gate_status=passed`, and 100%
  answer numeric support. `fabv2-pfe-sgen-transaction-multiple` is not
  repeatably closed yet. In `run_stable3_after_rescue` it reached live
  retrieval but produced no facts/claims/formula traces and reported
  `required_trace_missing`. A follow-up PFE-only rerun after planner-failure
  rescue still had `facts=0`, `claims=0`, `calculator_call_count=0`, and no
  verifier gate. The concrete failure chain was: some retrieval actions failed
  with a parser assertion (`unknown status keyword 'BZ' in marked section`),
  later acquisition fallback queries included unbound templates such as
  `{ticker}`, and the fast lane exhausted tool calls before a usable
  transaction evidence ledger existed. This should be treated as a
  retrieval/tool-observation, acquisition compiler, and planner-repair
  stability gap, not as a solved transaction-multiple case.
- The latest WSC add-back trend work deliberately tightened evidence gates so
  market-statistics snippets such as `EBITDA Margin` plus `Dividend Per Share`
  are no longer accepted as add-back/reconciliation evidence, and the natural
  fact ledger no longer projects those dividend/per-share snippets as EBITDA
  facts. The local regression set now covers these failures.
- The newest substrate/acquisition pass makes missing formula facts produce a
  generic `SlotFrame` plus `EvidencePolicy` in retrieval metadata. Retrieval
  document expansion now reads `required_evidence_terms`, `missing_slots`,
  `slot_frame`, and `evidence_policy` metadata as intent terms. For
  bridge/reconciliation tasks it now consistently prefers 10-K, 10-Q, 20-F, and
  40-F candidates before recent 8-K/6-K event filings even when the query names
  a target year. This is a task-family rule expressed through generic substrate
  metadata, not a WSC answer table.
- Reconciliation `SlotFrame` requirements now include `period_series` and
  `source_table` in addition to base, add-back, adjusted-metric, and optional
  deduction slots. The finance adapter can fill these slots from multi-period
  reconciliation evidence, and the formula planner now reports missing bridge
  inputs with the same slot names used by `SlotFrame` instead of separate
  internal labels.
- The latest WSC live rerun now closes the substrate path. The run
  `run_wsc_after_fallback_noise_fix` used `finance-fact-fast`, mission off,
  live retrieval, model planner, fake evaluator, and model synthesizer. It
  produced `retrieval_runs=1`, `fetches=8`, `download_mb=0.3` with cache hits,
  `finance_fact_count=108`, `calculator_call_count=1`, `formula_trace_count=1`,
  `numeric_verifier_status=passed`, `answer_numeric_support_rate=100%`,
  `citation_present_rate=100%`, and post-run dev annotation `overall_score=1.0`.
  This succeeded only after two fixes: SEC primary filing extraction now reads
  enough of large filing HTML to reach late non-GAAP tables, and finance
  fallback finalization produces a conservative cited answer when model
  synthesis returns invalid JSON.
- The WSC work also exposed a remaining design constraint: the first improved
  live run found `facts=186`, `calculator=1`, and `formula=1`, but failed
  because model synthesis returned invalid JSON and the fallback answer
  included noisy truncated evidence numbers. The fix keeps verifier standards
  intact by removing raw long evidence snippets from fallback answers, leaving
  numeric claims to calculator traces and ledger-backed facts.
- The latest rescue pass adds richer tool failure diagnostics (`error_message`,
  action id, payload keys, queries, and source URLs), host retrieval rescue after
  planner `processor_failed`, a leading-preposition target-parser repair so
  `For Pfizer` is not treated as an entity phrase, and an explicit finance
  numeric-claim policy in the synthesizer packet. These are generic reliability
  changes, not PFE answer tables.
- The current acquisition hardening pass fixes three concrete substrate
  failures exposed by PFE/SGEN repeatability runs:
  1. acquisition query templates are rendered against issuer/query metadata and
     unresolved placeholders such as `{ticker}` or `{company}` are skipped
     instead of sent to search;
  2. `retrieval.run` catches per-document extraction exceptions, records
     `extract_failed` diagnostics/rejected evidence, and continues processing
     other fetched documents;
  3. SEC event acquisition now treats transaction 8-K evidence as valid primary
     deal evidence, accepts SEC companyfacts as complementary slot evidence for
     transaction tasks, scans longer SEC filing bodies for late exhibit links,
     and seeds missing-fact retrieval with recognized issuers' SEC submissions
     and companyfacts URLs.
- Live PFE/SGEN after these fixes is improved but still not closed. The
  `run_pfe_sgen_after_complementary_companyfacts` run reached the Pfizer 8-K
  and Seagen companyfacts, with `facts=46`, `claims=46`, `slot_frame_present=1`,
  `transform_plan_present=1`, `verifier_gate=passed`, and 100% numeric support,
  but `calculator_call_count=0` because the total transaction EV was not in the
  accepted facts. The later `run_pfe_sgen_after_sec_seed_urls` run reached the
  Pfizer 8-K and produced `facts=10`, `claims=10`, but still lacked the total
  EV and revenue slots together. This is now classified as an event-source /
  exhibit acquisition gap, not a formula, verifier, or prompt-format issue.
- 2026-06-10 SEC exhibit acquisition pass:
  `retrieval.run` now expands SEC complete-submission text into child exhibit
  documents, treats `sec_exhibit_document` as a filing-text source kind, gives
  EX-99 / press-release children higher transaction relevance than EX-2 merger
  agreements, reserves one second-hop fetch slot for transaction filing
  expansion, and lets evidence evaluation match transaction synonyms such as
  `EV` / `enterprise value`, `acquisition`, `acquire`, `acquired`, and
  `merger`. Local regressions for document expansion, retrieval campaigns, deep
  retrieval, finance engine, and finance benchmark passed with `134 passed`.
  The PFE-only live reruns after this change improved source acquisition but
  still did not close repeatably. The best post-change PFE reruns reached SEC
  transaction filing sources and produced `facts=16`, `claims=16`,
  `slot_frame_present=1`, and `transform_plan_present=1`, but still had
  `calculator_call_count=0`, `formula_trace_count=0`, and four missing slots
  (`equity_value_or_market_cap`, `debt`, `cash`, `revenue`). One rerun fetched
  and accepted the merger agreement exhibit (`d408093dex21.htm`) plus the
  primary 8-K (`d408093d8k.htm`), but did not yet acquire/bind the press-release
  enterprise-value disclosure as a usable finance fact. This keeps PFE/SGEN in
  the source-acquisition / fact-ledger binding bucket rather than the formula or
  verifier bucket.
- 2026-06-10 stable4 delivery rerun after the SEC exhibit acquisition pass:
  `run_stable4_latest_after_pfe_acquisition_fixes` used `finance-fact-fast`,
  mission off, live retrieval, model planner, fake evaluator, model synthesizer,
  compact context, and `parallel=1` on HD/LOW DIO, KHC adjusted EBITDA bridge,
  PFE/SGEN transaction multiple, and WSC adjusted EBITDA add-back trend. The
  batch produced `overall_score=0.9603`, behavior score `0.9643`, substrate
  score `0.9167`, numeric score `1.0`, calculator-used rate `0.75`,
  formula-trace-present rate `0.75`, numeric-verifier pass rate `1.0`,
  claim-ledger present rate `1.0`, slot-frame present rate `1.0`,
  transform-plan present rate `1.0`, verifier-gate pass rate `1.0`,
  citation-present rate `1.0`, average answer numeric support `1.0`, average
  retrieval runs `1.5`, average total tokens `78,233.25`, average duration
  `57,108.25 ms`, average finance facts `86.5`, average claims `86.5`, average
  calculator calls `1.5`, average formula traces `1.5`, and average missing
  slots `1.25`. HD/LOW DIO closed with `facts=40`, `claims=40`,
  `calculator_call_count=4`, `formula_trace_count=4`, verifier passed, and
  post-run behavior/numeric/substrate scores all `1.0`. KHC closed with
  `facts=147`, `claims=147`, one calculator trace, no missing slots, verifier
  passed, and substrate score `1.0`. WSC closed with `facts=143`,
  `claims=143`, one calculator trace, no missing slots, verifier passed, and
  substrate score `1.0`. PFE/SGEN remained the only non-closed representative:
  `retrieval_runs=3`, `fetches=32`, `facts=16`, `claims=16`,
  `calculator_call_count=0`, `formula_trace_count=0`, four missing slots, and
  post-run substrate score `0.6667`. This stable4 result is the current
  delivery-grade checkpoint; it should be reported as a strong auditable
  substrate demonstration, not as a solved official FAB v2 benchmark.
- 2026-06-10 EventSourceResolver v1 and SynthesisGate v1 delivery pass:
  SEC submissions expansion now derives a first-class EX-99.1 event-disclosure
  candidate for transaction 8-K filings from the primary document stem
  (`sec_transaction_exhibit_from_submission_v1`). This is a generic event-source
  resolver rule for SEC transaction events; it does not encode answer values.
  The same pass adds an explicit `synthesis_gate_result` journal record and
  benchmark metric. For finance answers, the gate enforces that material numeric
  claims must be backed by `ClaimLedger` facts, formula/transform traces, or
  explicit assumptions; unsupported numbers trigger fallback or failure instead
  of passing through synthesis.
- PFE/SGEN is now repeatably closed in the latest live checks. The PFE-only run
  `run_pfe_sgen_event_resolver_v1` completed with `retrieval_runs=1`,
  `fetches=8`, `finance_fact_count=40`, `claim_count=40`,
  `calculator_call_count=1`, `formula_trace_count=1`, `missing_slots=0`,
  `transform_plan_count=2`, `numeric_verifier_status=passed`,
  `verifier_gate_status=passed`, and 100% answer numeric support. The full
  dev10 rerun also closed PFE/SGEN with `retrieval_runs=1`, `fetches=8`,
  `facts=29`, `claims=29`, `calculator_call_count=1`,
  `formula_trace_count=1`, `missing_slots=0`, and both verifier gates passed.
  This moves PFE/SGEN out of the active source-acquisition gap bucket and into
  the stable showcase bucket, while still keeping the mechanism generic.
- Latest full curated dev10 live rerun:
  `run_dev10_event_resolver_v1` used `finance-fact-fast`, mission off, live
  retrieval, model planner, fake evaluator, model synthesizer, compact context,
  and `parallel=1`. The run produced post-run dev annotation
  `overall_score=0.9056`, behavior score `0.9167`, substrate score `0.8`,
  numeric score `1.0`, calculator-used rate `0.4`,
  formula-trace-present rate `0.4`, numeric-verifier pass rate `0.5`,
  verifier-gate pass rate `0.5`, synthesis-gate pass rate `0.5`,
  claim-ledger present rate `1.0`, slot-frame present rate `1.0`,
  transform-plan present rate `1.0`, citation-present rate `0.6`, average
  answer numeric support `0.7953`, average retrieval runs `1.0`, average total
  tokens `61,422.7`, average finance facts `71.4`, and average claims `71.4`.
  The first four representative workflow items all closed: HD/LOW DIO,
  KHC adjusted EBITDA bridge, PFE/SGEN transaction multiple, and WSC adjusted
  EBITDA add-back trend. The remaining six items mainly fail by
  `required_trace_missing` or `unsupported_answer_number`: CRM DCF, EPAM LBO,
  TGT/WMT fixed-charge coverage, LULU/VSCO EV/EBITDA, CNC MLR rebate, and
  PFE/Seagen purchase-price allocation. These are now best classified as
  transform-planning / formula-template / modeling-policy gaps, not source
  acquisition failures.
- 2026-06-11 workflow-harness scoring pass:
  curated dev10 items and scoring annotations now carry structured workflow
  annotations. `trace_metrics`, `FinanceBenchmarkSummary`, behavior graph diagnostics,
  CLI progress, and finance reports now expose workflow-oriented metrics including
  synthesis-gate repair rate, citation preservation rate, unsupported numeric claim
  rate, missing-slot recovery rate, cost per passed item, repeatability score when
  duplicate item runs are present, workflow type counts, and workflow annotation
  scores. Re-scoring the existing live dev10 results with
  `run_dev10_event_resolver_v1.workflow_scored` yields `overall_score=0.9114`,
  behavior `0.9167`, substrate `0.8889`, workflow `0.8399`, numeric `1.0`,
  unsupported numeric claim rate `0.4`, citation preservation `0.6`, and workflow
  type scores that identify coverage ratio, modeling-lite, and valuation multiple
  as the next pressure points. This pass did not rerun the agent; it re-evaluated the
  latest live outputs with the stricter workflow harness.
- The official FAB v2 public file was downloaded to `data/raw/fabv2_public.txt` and
  imported to `data/bench/finance/fabv2_public.jsonl` (`27` items, `0` skipped). The
  importer now adds workflow annotations to public questions where possible, so public27
  can be used as a behavior/substrate/cost/failure-taxonomy run without putting gold or
  rubrics into prompts.
- Public27 live workflow baseline:
  `run_public27_workflow_v1` ran all 27 public questions with `finance-fact-fast`,
  mission off, live retrieval, model planner, fake evaluator, model synthesizer,
  compact context, and `parallel=1`. The set has no public gold, so every item is
  `ungraded_no_gold_signal`; report it as a generalization health check, not an
  official accuracy score. Summary: answer-present rate `1.0`, claim-ledger /
  slot-frame / transform-plan present rates `0.6296`, calculator-used rate `0.2222`,
  formula-trace-present rate `0.2222`, citation preservation `0.2593`,
  numeric-verifier pass rate `0.0909`, verifier-gate pass rate `0.0909`,
  synthesis-gate pass rate `0.1111`, unsupported numeric claim rate `0.3704`,
  average answer numeric support `0.4456`, average retrieval runs `2.2593`,
  average fetches `18.8148`, average downloaded bytes `43.6MB`, and average total
  tokens `87,928.4`. Workflow type distribution: source-grounded research `14`,
  reconciliation `7`, event transaction `3`, modeling-lite `1`,
  multi-entity compute/compare `1`, valuation multiple `1`. The main failure modes
  are `all_evidence_rejected`, `coverage_gap`, and
  `finance_numeric:unsupported_answer_number`.
- Finance Workflow RC report artifacts were regenerated on 2026-06-11 and should
  be treated as the frozen handoff baseline before further live experimentation:
  `.state/kernel_v3/bench/finance/run_stable4_event_resolver_v1.report.md`,
  `.state/kernel_v3/bench/finance/run_dev10_event_resolver_v1.report.md`,
  `.state/kernel_v3/bench/finance/run_dev10_event_resolver_v1.workflow_report.md`,
  and `.state/kernel_v3/bench/finance/run_public27_workflow_v1.report.md`.
  The frozen headline metrics remain stable4 overall `0.9603`, live dev10
  overall `0.9056`, workflow-rescore overall `0.9114`, and public27 as an
  ungraded health check.
- RC hardening has started on the two public27 generalization gaps only. First,
  generic source-grounded retrieval finalization now journals a domain-neutral
  `claim_ledger`, `slot_frame`, and `transform_plan` for qualitative/source-
  grounded tasks whenever retrieval evidence exists, even when no finance
  formula is applicable. Second, the finance SynthesisGate now has a
  citation-preserving conservative fallback when model synthesis inserts
  unsupported material numbers: unsupported numeric claims are stripped or
  downgraded into limitations, citation refs are preserved, and the fallback is
  accepted when deterministic verification finds no unsupported material
  numeric claim. These changes are local-tested; a fresh public27 live rerun is
  still required before updating the public27 baseline metrics.
- `data/bench/finance/holo_finance_workflow_challenge.jsonl` now adds a 50-item
  taxonomy challenge set by workflow shape instead of company. It is designed to
  stop the project from overfitting to dev10 while still keeping every task tied
  to a generic workflow primitive and trace expectation.
- Future validation should keep the same failure taxonomy discipline: classify
  failures as source acquisition, fetch/parser, fact-ledger extraction, formula
  binding, verifier policy, synthesis gate, or model JSON repair before adding
  any task-specific heuristic.
- Fast-lane cost is still high. Successful single-item runs often consume
  60k-90k tokens, and hard cases can fail after model JSON repair issues. The
  next executor work should shrink planner/evaluator context for finance facts,
  keep retrieval diagnostics compact, and make processor budget failures return
  actionable host replan hints instead of repeated `respond` fallbacks.

## Next Steps

1. Keep HD/LOW DIO, KHC adjusted EBITDA bridge, PFE/SGEN transaction multiple,
   and WSC adjusted EBITDA add-back trend as the stable delivery showcase. These
   four demonstrate the general slot/evidence/claim/transform/verifier workflow
   in finance form.
2. Use public27 as the external generalization baseline. The current code now
   targets the two intended gaps only: generic source-grounded `ClaimLedger` /
   `SlotFrame` / `TransformPlan` traces for qualitative disclosure tasks, and
   SynthesisGate repair for numeric tasks with partial support. The next action is
   a fresh public27 live rerun to see whether citation preservation moves toward
   `0.6+`, synthesis-gate pass rate toward `0.4+`, unsupported numeric claim rate
   below `0.2`, and claim/slot/transform present rate toward `0.75+`. Because
   public27 has no public gold, do not call it an official accuracy score.
3. Do not broaden new architecture before addressing the dev10 failure taxonomy.
   The next substrate work should target remaining transform-planning /
   modeling-policy gaps that appear across several tasks: fixed-charge
   coverage, MLR rebate, purchase price allocation, and stronger market-data
   acquisition for EV/EBITDA. DCF/LBO now have a first deterministic
   modeling-lite transform planner and fresh single-item reruns show formula
   traces; the dev10 status should still remain blocked until SynthesisGate
   produces assumption-labeled, citation-preserving answers without unsupported
   numeric claims.
4. Add domain-pack formula templates and slot schemas only when they map to a
   reusable workflow primitive: valuation model, coverage ratio, regulatory
   rebate calculation, or purchase-price-allocation reconciliation. Do not add
   item-specific answer heuristics.
5. Improve `SynthesisGate` repair so failed gates can either remove unsupported
   material numbers or produce a concise limitation answer with the missing
   transform slots, instead of relying on model synthesis to self-correct.
6. Map reconciliation `period_series` / `source_table` gaps into more explicit
   ledger extraction diagnostics and missing-slot replan hints, especially when
   the source contains a table but the fact ledger extracts no add-back rows.
7. Run the curated dev10 in small batches and classify verifier failures into
   unsupported answer number, ledger extraction gap, missing formula trace, unit
   mismatch, period mismatch, and assumption-label issues.
8. Expand the finance fact ledger and formula planner for fixed-charge
   coverage, MLR, and purchase price allocation cases. DCF/LBO v1 now binds
   cash-flow / entry-value facts to explicit modeling assumptions and emits
   calculator payloads. EV/EBITDA now has formula intent and missing-fact
   fallback; it still needs stronger acquisition for market cap, total debt,
   cash, and EBITDA components.

## 2026-06-11 Modeling-Lite Substrate Update

This iteration adds deterministic DCF/LBO support to the generic workflow
spine, without adding fixed-answer benchmark heuristics:

- `FinanceFactLedger` now recognizes operating cash flow, free cash flow, net
  cash provided by operating activities, and capital expenditures from
  structured facts and natural text.
- `FinanceFormulaPlanner` now detects DCF and LBO intents. DCF binds free cash
  flow directly, or derives base free cash flow from operating cash flow less
  capital expenditures when both are available. LBO binds entry enterprise
  value, EBITDA, leverage, exit multiple, EBITDA growth, debt-paydown, and hold
  period into a sponsor-IRR calculator trace.
- DCF/LBO assumptions are carried in diagnostics as `question_or_host_modeling_policy`
  assumptions. This keeps generated numbers auditable and lets SynthesisGate
  require explicit assumption labeling.
- `SlotFrame` and `EvidencePolicy` now represent modeling-lite tasks directly:
  DCF exposes `base_cash_flow`, `growth_assumptions`, `discount_rate`, and
  `terminal_value_assumption`; LBO exposes `entry_value`, `debt_assumption`,
  `cash_flow_or_ebitda`, and `exit_assumption`.
- Missing DCF/LBO slots now feed targeted retrieval hints for SEC filings,
  companyfacts, investor materials, cash-flow inputs, WACC / terminal growth,
  EBITDA, leverage, exit multiple, debt, and cash.

Verification so far is local regression plus targeted live checks, not a new
full dev10 score:
`tests/test_kernel_v3_finance_engine.py` covers DCF and LBO calculator payloads,
derived free-cash-flow inputs, modeling slot frames, and missing-slot retrieval
payloads. The broader finance benchmark / retrieval provider regression suite
also passes. The live CRM DCF / EPAM LBO reruns below prove the paths enter the
real loop, but they do not yet justify upgrading dev10 scores.

Live follow-up:

- `run_modeling_lite_dcf_lbo_v1` ran CRM DCF and EPAM LBO. CRM DCF reached
  `retrieval_runs=1`, `calculator_call_count=1`, `formula_trace_count=1`,
  `finance_fact_count=106`, and `claim_count=106`, proving the DCF transform
  entered the real loop. It still failed numeric verification due to unsupported
  final-answer numbers.
- EPAM LBO initially still had no calculator trace because retrieval found
  revenue/debt/cash-style facts but no EBITDA or cash-flow basis. The LBO
  planner was then extended to use a clearly labeled `revenue * EBITDA margin`
  modeling assumption when no direct EBITDA / cash-flow basis is available.
- `run_epam_lbo_after_revenue_margin_fallback_v1` then produced
  `calculator_call_count=1`, `formula_trace_count=1`, `transform_plan_count=2`,
  `claim_ledger_present_rate=1.0`, and `substrate_score=0.8889`. It still failed
  verifier / synthesis gates because material numeric claims need stronger
  assumption separation and unsupported-number stripping before final answer
  delivery.

Conclusion: DCF/LBO are now real modeling-lite substrate paths with live
calculator traces, but they are not yet solved benchmark items. The next
engineering pressure should move from formula coverage to SynthesisGate repair,
assumption-ledger display, and citation-preserving limitation answers.

2026-06-11 DCF/LBO trace hardening:

- `calculator.compute` now accepts optional planner diagnostics and preserves
  them inside `FormulaTrace`, so modeling runs can carry schedules and
  assumption provenance through the same calculator/journal path as simpler
  ratios.
- DCF planning now builds an auditable model schedule: projected free cash flow,
  discount factor, present value by year, terminal free cash flow, terminal
  value, PV of terminal value, enterprise value, net debt, equity value, and
  optional equity value per share. It uses a precise cash selector so operating
  cash flow is not mistaken for cash on hand.
- LBO planning now emits an auditable debt and exit schedule: entry enterprise
  value, initial debt, sponsor equity, annual EBITDA, debt paydown, ending debt,
  exit EV, exit debt, exit equity, MOIC, and sponsor IRR. These outputs are
  diagnostics attached to the formula trace; retrieved facts and assumptions
  remain distinguishable.
- DCF/LBO output selection now matches the question-level target: DCF can report
  enterprise value, equity value, or equity value per share; LBO can report
  sponsor IRR, MOIC, or exit equity value. The selected value becomes the actual
  `calculator.compute` result, not just a secondary diagnostics field.
- The finance numeric verifier now accepts model-output diagnostics and explicit
  assumptions as calculator-derived support values, including percentage display
  forms such as `9%` for a stored `0.09` assumption. The conservative host
  fallback summarizes DCF/LBO core outputs and labels modeling assumptions when
  the model synthesizer inserts unsupported numbers.
- This improves model auditability and answer repair, but it does not by itself
  upgrade CRM DCF / EPAM LBO benchmark status. A new live run is still required
  to measure the end-to-end score impact.

Additional follow-ups:

- Reduce `finance-fact-fast` cost by shrinking processor prompts, using
  structured retrieval results more directly, and avoiding synthesis context
  duplication.
- Add repeated-run stability batches for stable4/dev10: each selected item
  should run at least three times and report source-family, claim-count,
  slot-missing, calculator-trace, verifier-gate, synthesis-gate, and final
  status stability.
- Add claim-level citation judging for non-numeric assertions.
- Add source-support scoring against benchmark evidence excerpts.
- Add PPT-ready rendering presets for task and benchmark graphs.
- Add ablation presets: bare LLM, simple retrieval, Holo retrieval, Holo
  retrieval plus memory.
