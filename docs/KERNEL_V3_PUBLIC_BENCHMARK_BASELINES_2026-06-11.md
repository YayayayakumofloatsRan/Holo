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

That true path has now been probed on a small live 3-item subset
(`run_financebench_doc_retrieval_live_limit3_v1`). It performed real retrieval
work (`1.3333` average retrieval runs; each item fetched `8` to `16` sources)
but still scored `0/3`: no finance facts, citations, calculator traces, or
formula traces were produced. This is the current source-acquisition /
document-extraction gap for FinanceBench doc retrieval.

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
2. Improve FinanceBench `doc_retrieval` source acquisition before expanding the
   live subset: the live3 probe already retrieves documents, but does not
   convert them into citable facts or calculator inputs.
3. Run FinQA oracle-context `500` only after formula/target binding improves on
   oracle100. Otherwise it will mainly multiply known failures.
4. Keep dev10/public27 as workflow regression and generalization checks, but do
   not present them as official public benchmark accuracy.
