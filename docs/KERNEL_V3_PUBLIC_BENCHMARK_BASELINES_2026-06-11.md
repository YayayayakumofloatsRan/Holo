# Holo Kernel v3 Public Benchmark Baselines

Date: 2026-06-11

This document records the first public gold-backed baseline runs after the
FinanceBench and FinQA import/download plumbing landed. These runs are
benchmarks of the current workflow substrate and scoring path, not final public
leaderboard claims.

Gold/reference answers and justifications remain scoring-only sidecars. They
are not inserted into Holo prompts.

## Scope

| Slice | Purpose | Artifact |
| --- | --- | --- |
| dev10 RC | curated workflow regression | `.state/kernel_v3/bench/finance/run_dev10_event_resolver_v1.summary.json` |
| dev10 workflow rescore | stricter trace/workflow score | `.state/kernel_v3/bench/finance/run_dev10_event_resolver_v1.workflow_scored.summary.json` |
| public27 | ungraded FAB v2 public health check | `.state/kernel_v3/bench/finance/run_public27_workflow_v1.summary.json` |
| FinanceBench-150 oracle evidence | gold-backed filing QA with benchmark evidence excerpt supplied as prompt context | `.state/kernel_v3/bench/finance/run_financebench_150_oracle_evidence_fake_v1.summary.json` |
| FinanceBench-150 doc retrieval | no-network negative-control run with document metadata only; not a capability score | `.state/kernel_v3/bench/finance/run_financebench_150_doc_retrieval_fake_v1.summary.json` |
| FinanceBench doc retrieval live3 | small live source-acquisition probe | `.state/kernel_v3/bench/finance/run_financebench_doc_retrieval_live_limit3_v1.summary.json` |
| FinQA dev oracle100 | gold-backed numeric reasoning with benchmark context supplied as prompt context | `.state/kernel_v3/bench/finance/run_finqa_dev_oracle100_fake_v1.summary.json` |

The FinanceBench and FinQA runs below used fake processors and no network/live
retrieval. They validate the public benchmark normalization, scoring, oracle
context ingestion, and deterministic substrate paths. They do not measure live
model research quality.

## Results

| Benchmark slice | Items | Pass / accuracy | Workflow score | Substrate score | Calculator / formula | Citations | Unsupported numeric |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| dev10 live RC | 10 | annotated overall `0.9056`; numeric `1.0` | n/a | `0.8` | `0.4` / `0.4` | citation-present `0.6` | n/a |
| dev10 workflow rescore | 10 | annotated overall `0.9114`; numeric `1.0` | `0.8399` | `0.8889` | `0.4` / `0.4` | preservation `0.6` | `0.4` |
| public27 health check | 27 | ungraded | n/a | claim/slot/transform `0.6296` | `0.2222` / `0.2222` | preservation `0.2593` | `0.3704` |
| FinanceBench-150 oracle evidence fake | 150 | pass `0.2`; numeric accuracy `0.2381` | `0.9132` | `1.0` | `0.14` / `0.14` | preservation `0.8733` | `0.1067` |
| FinanceBench-150 doc retrieval fake | 150 | pass `0.0067`; numeric accuracy `0.0079` | `0.8059` | `0.7037` | `0.0` / `0.0` | preservation `0.0` | `0.0` |
| FinanceBench doc retrieval live3 | 3 | pass `0.0`; numeric accuracy `0.0` | `0.8571` | `0.8571` | `0.0` / `0.0` | preservation `0.0` | `0.0` |
| FinanceBench doc retrieval live3 target-binding v2 | 3 | pass `0.6667`; numeric accuracy `0.6667` | `0.9048` | `1.0` | `0.0` / `0.0` | preservation `0.6667` | `0.3333` |
| FinanceBench doc retrieval live3 target-slots v4 | 3 | pass `1.0`; numeric accuracy `1.0` | `1.0` | `1.0` | `0.3333` / `0.3333` | preservation `1.0` | `0.0` |
| FinanceBench doc retrieval live3 model-net v1 | 3 | pass `1.0`; numeric accuracy `1.0` | n/a | claim/slot/transform `1.0` | `0.3333` / `0.3333` | preservation `1.0` | `0.0` |
| FinanceBench doc retrieval live10 target-slots v1 | 10 | pass `0.30`; numeric accuracy `0.30` | `0.6572` | `0.60` | `0.20` / `0.20` | preservation `0.40` | `0.0` |
| FinanceBench doc retrieval item4 model-net v6 | 1 | pass `0.0`; behavior `1.0`; source missing cleared | `1.0` | `1.0` | `0.0` / `0.0` | preservation `1.0` | `0.0` |
| FinanceBench doc retrieval item4 model-net v7 | 1 | post-fix scorer failed; old pass was a false positive | diagnostic only | `1.0` | `0.0` / `0.0` | preservation `0.0` | `1.0` |
| FinanceBench doc retrieval item4 model-net v15 | 1 | pass `0.0`; trace complete; expected `1.7` not matched | `0.7143` | `1.0` | `0.0` / `0.0` | preservation `0.0` | `1.0` |
| FinanceBench doc retrieval item4 model-net v17 | 1 | pass `0.0`; trace complete; evidence selection still wrong | `0.7143` | `1.0` | `0.0` / `0.0` | preservation `0.0` | `1.0` |
| FinQA dev oracle100 fake | 100 | pass `0.15`; numeric accuracy `0.15` | `0.925` | `0.8816` | `0.37` / `0.37` | preservation `0.92` | `0.06` |

## Interpretation

FinanceBench oracle evidence is the first full public gold-backed 150-row run.
It shows the generic workflow spine is active on all rows:
claim ledger, slot frame, transform plan, verifier gate, and synthesis gate are
present at `1.0`. The main gap is numerical target selection and calculator
binding: `expected_numeric_mismatch` appears on `100` items, and only `14%` of
items use a calculator/formula trace.

FinanceBench doc retrieval was run once as a no-network negative control, not as
a capability score. The prompt contains document metadata rather than evidence
excerpts, and the run does not perform live document acquisition. Its `0.0067`
pass rate only confirms that the harness does not fabricate answers when the
required document evidence is absent. True `doc_retrieval` must be rerun with
live retrieval/document fetching before it represents Holo's source-acquisition
ability.

That true path was first probed on a small live 3-item subset
(`run_financebench_doc_retrieval_live_limit3_v1`). It performed real retrieval
work (`1.3333` average retrieval runs; each item fetched `8` to `16` sources)
but still scored `0/3`: no finance facts, citations, calculator traces, or
formula traces were produced. This is the current source-acquisition /
document-extraction baseline for FinanceBench doc retrieval. A later focused
target-binding probe, `run_financebench_doc_live3_binding_v2`, improves the
same first-three-item slice to `2/3`: item 2 closes after inline
`Document period` parsing and balance-sheet net PP&E / net PPNE binding to SEC
`PropertyPlantAndEquipmentNet`. Item 3 remains a capital-intensity workflow gap
requiring missing slot recovery and a supported transform.
Task Compiler v1 keeps the same live3 slice at `2/3`, but adds a first-class
program trace: compiled task program presence is `1.0`, and item 3 is compiled
as a `compute` task with five evidence specs, three capital-intensity transform
specs, and explicit missing slots for capex, operating cash flow, net PP&E, and
assets. This makes the next doc-retrieval work a slot/transform binding problem
rather than an undefined search-threshold problem.

The target-slot binding pass closes that small slice:
`run_financebench_doc_live3_target_slots_v4` reaches `3/3`. The third item now
preserves target-bound FY2022 SEC companyfacts evidence for revenue, operating
cash flow, capex, net PP&E, and assets; the host calculator computes
`capital_expenditures / revenue = 5.1097%`; numeric verifier, verifier gate, and
synthesis gate all pass; citation preservation is `1.0`. The broader live10
baseline, `run_financebench_doc_live10_target_slots_v1`, is still only `3/10`.
That result is useful because failures are no longer hidden behind the first
three rows: later rows mostly fail before claim ledger creation because the
document/table reader and source resolver do not yet extract the needed Adobe
and 3M 10-Q/10-K tables, while a disclosure-style row retrieves facts but needs
source-grounded qualitative answer handling instead of numeric fallback.

The closed first slice was revalidated with true model/network access in
`run_financebench_doc_live3_model_net_v1`: pass rate and numeric accuracy remain
`1.0`, citation preservation is `1.0`, unsupported numeric claim rate is `0`,
and average retrieval runs are `1.3333`. The fourth-row follow-up is more
instructive than its raw status: `run_financebench_doc_item4_model_net_v6`
forces a second retrieval from the model Workbench's semantic missing slots,
clears the required `investors.3m.com` source miss, and reaches behavior /
workflow / substrate score `1.0`, but still fails numeric scoring because the
source-grounded synthesis path does not yet produce the required operating
margin-change explanation. `run_financebench_doc_item4_model_net_v7` exposed a
scorer false positive: the old numeric extractor treated the company token `3M`
as `3,000,000`, so a failure report could pass against the wrong gold numeric.
The scorer now rejects that pattern and requires a real final answer for
non-sentinel gold-backed rows; v7 re-scores as failed and should be reported
only as a diagnostic showing why the internal gates matter.

The follow-up item4 runs v15 through v17 show real loop progress but no score
claim. The Workbench semantic follow-up is now honored for four retrieval runs,
planner JSON repair failures no longer hide a partial retrieval finalization
path, and the source-grounded workflow trace is complete. v17 records finance
facts / claims `22`, transform plans `5`, compiled task program present `1.0`,
required trace hit `7/7`, and substrate score `1.0`. It still fails because the
material answer is unsupported: citation preservation is `0`, numeric verifier
and synthesis gate fail, expected numeric `1.7` is not matched, and the selected
evidence remains `data.sec.gov` companyfacts rather than target filing MD&A
discussion. The SEC archive URL resolver is active, but document block selection
and source-grounded synthesis are still the blocking FinanceBench doc-retrieval
work.

FinQA dev oracle100 confirms the FinQA oracle-context path scales beyond the
earlier 20-row diagnostic, but the score drops from the small oracle20 sample:
numeric accuracy is `0.15`, calculator/formula trace rate is `0.37`, and the
dominant failure remains `expected_numeric_mismatch`. The high citation
preservation (`0.92`) and low unsupported-number rate (`0.06`) indicate the
answer grounding path is working; the weakness is formula/target binding.

## Next Runs

1. Run a small live-model FinanceBench oracle subset before attempting live 150:
   `--limit 10`, `finance-fact-fast`, mission off, fake evaluator, model planner
   and synthesizer.
2. Improve FinanceBench `doc_retrieval` beyond the now-closed first live3 slice:
   focus on target PDF/table extraction, company filing URL/CIK resolution for
   non-3M documents, and source-grounded qualitative disclosure tasks. The
   current live10 baseline is `3/10`.
3. Run FinQA oracle-context `500` only after formula/target binding improves on
   oracle100. Otherwise it will mainly multiply known failures.
4. Keep dev10/public27 as workflow regression and generalization checks, but do
   not present them as official public benchmark accuracy.
