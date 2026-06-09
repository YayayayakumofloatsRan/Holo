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
- `secque`: question, answer/ground truth, SEC filing context/supporting data, accession,
  page/item/section metadata.
- `financeqa`: question, answer, filing context, question type, company, file link/name.
- `finqa`: report text/table context, answer, and numerical-reasoning annotations.

Import policy:

- gold answers are scoring-only and are never inserted into the agent prompt;
- rubrics and reference chain-of-thought/program annotations are scoring-only;
- benchmark-provided filing/report context may be inserted into the prompt as evidence;
- every import can write a manifest with source URL, prompt policy, item count, and warnings.

## CLI

Run Holo against a JSONL benchmark:

```bash
HOLO_V3_LIVE_MODEL=1 ./holo-v3 bench finance \
  --dataset data/finagent.jsonl \
  --limit 10 \
  --online \
  --research-profile finance_fundamentals \
  --research-depth deep \
  --live-retrieval \
  --live-search-strategy adaptive
```

Score existing predictions without running Holo:

```bash
./holo-v3 bench finance \
  --dataset data/finagent.jsonl \
  --predictions artifacts/finance_predictions.jsonl \
  --output artifacts/finance_bench_results.jsonl \
  --summary-output artifacts/finance_bench_summary.json
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
- adversarial/unavailable-answer accuracy,
- average token use,
- average processor duration,
- average retrieval runs,
- average query repetition rate.

## Next Steps

1. Add optional authenticated download helpers for HuggingFace-hosted datasets, while keeping
   import/scoring runnable from local exports.
2. Add claim-level citation judge for answers whose gold target is not purely numeric.
3. Add source-support scoring against benchmark evidence excerpts.
4. Add a behavior graph view: question -> subgoal -> query -> source -> document -> evidence -> claim -> answer.
5. Add ablation presets: bare LLM, simple retrieval, Holo retrieval, Holo retrieval plus memory.
