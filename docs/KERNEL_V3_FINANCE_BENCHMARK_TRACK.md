# Kernel v3 Finance Benchmark Track

This track turns the submitted Holo project proposal into a measurable implementation plan.
The goal is not to demonstrate a hand-picked chat transcript, but to evaluate Holo as an
evidence-governed financial research harness on external benchmark questions.

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
- `secque`: question, answer/ground truth, SEC filing context/supporting data, accession,
  page/item/section metadata.
- `financeqa`: question, answer, filing context, question type, company, file link/name.
- `finqa`: report text/table context, answer, and numerical-reasoning annotations.

Import policy:

- gold answers are scoring-only and are never inserted into the agent prompt;
- rubrics and reference chain-of-thought/program annotations are scoring-only;
- benchmark-provided filing/report context may be inserted into the prompt as evidence;
- every import can write a manifest with source URL, prompt policy, item count, and warnings.

Finance Agent v2 public import:

```bash
./holo-v3 bench finance-import \
  --benchmark finance_agent_v2_public \
  --input data/raw/fabv2_public.txt \
  --output .state/kernel_v3/bench/finance/fabv2_public_dev.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/fabv2_public_dev.manifest.json
```

The official public file lives at
`https://raw.githubusercontent.com/vals-ai/finance-agent-v2/main/data/public.txt`.
Keep it as a local input for reproducible runs and to avoid accidental repeated downloads.

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
- average query repetition rate.

The report renderer turns item results into Markdown, HTML, or JSON with:

- score and efficiency summary,
- status, failure-mode, and score-reason breakdowns,
- weakest items ranked by score, citations, trace cost, repetition, and answer length,
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
- The next concrete live validation should first fix acquisition compiler
  placeholder binding and SEC parser robustness for the PFE/SGEN path, then
  rerun PFE/SGEN and finally rerun KHC/WSC/PFE-SGEN together. If a case fails,
  classify the failure as source acquisition, fetch/parser, fact-ledger
  extraction, formula binding, verifier policy, or model-synthesis/JSON repair
  before adding any new task-specific heuristic.
- Fast-lane cost is still high. Successful single-item runs often consume
  60k-90k tokens, and hard cases can fail after model JSON repair issues. The
  next executor work should shrink planner/evaluator context for finance facts,
  keep retrieval diagnostics compact, and make processor budget failures return
  actionable host replan hints instead of repeated `respond` fallbacks.

## Next Steps

1. Rerun KHC/WSC/PFE-SGEN as a small live batch and confirm that each item
   records evidence, facts, formula traces, citations, and numeric verification
   after the KHC scale repair. Keep the gold/dev annotations out of prompts.
2. Map reconciliation `period_series` / `source_table` gaps into more explicit
   ledger extraction diagnostics and missing-slot replan hints, especially when
   the source contains a table but the fact ledger extracts no add-back rows.
3. Run the curated dev10 in small batches and classify verifier failures into
   unsupported answer number, ledger extraction gap, missing formula trace, unit
   mismatch, period mismatch, and assumption-label issues.
4. Expand the finance fact ledger and formula planner for bridge, transaction
   multiple, fixed-charge coverage, DCF/LBO, MLR, and purchase price allocation
   cases. EV/EBITDA now has formula intent and missing-fact fallback; it still
   needs stronger acquisition for market cap, total debt, cash, and EBITDA
   components.
5. Add an event-aware finance filing resolver for transaction questions:
   identify issuer/target, likely announcement/closing periods, SEC accession
   candidates, and whether the task needs 8-K, merger agreement, 10-K note, or
   investor/press-release evidence.
6. Reduce `finance-fact-fast` cost by shrinking processor prompts, using
   structured retrieval results more directly, and avoiding synthesis context
   duplication.
7. Add claim-level citation judging for non-numeric assertions.
8. Add source-support scoring against benchmark evidence excerpts.
9. Add PPT-ready rendering presets for task and benchmark graphs.
10. Add ablation presets: bare LLM, simple retrieval, Holo retrieval, Holo
   retrieval plus memory.
