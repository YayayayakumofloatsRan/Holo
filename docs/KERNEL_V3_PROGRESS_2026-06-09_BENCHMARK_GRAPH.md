# Kernel v3 Progress: Public Benchmarks and Behavior Graphs

Date: 2026-06-09

## What Changed

Kernel v3 now has a public-finance benchmark import path and a task behavior
graph export path.

The benchmark import path normalizes local CSV/JSON/JSONL exports from:

- Finance Agent Benchmark,
- SECQUE,
- FinanceQA,
- FinQA.

The import writes Kernel v3 benchmark JSONL plus an optional provenance
manifest. Gold answers, rubrics, reference chain-of-thought, and reference
program annotations are recorded for scoring/audit only and are not inserted
into agent prompts. Benchmark-provided filing/report context can enter the
prompt as source context.

The behavior graph path exports a journal-derived graph for a task:

```text
task -> processor calls -> action -> retrieval query/source/fetch/document
     -> evidence -> citation -> feedback -> final answer/failure report
```

It is available as JSON or Graphviz DOT:

```bash
holo-v3 behavior-graph <task_id> --format json
holo-v3 behavior-graph <task_id> --format dot --output graph.dot
```

Benchmark result graphs summarize many benchmark rows without needing the
worker journals:

```bash
holo-v3 bench finance-graph \
  --results artifacts/finance_bench_results.jsonl \
  --format dot \
  --output finance_bench.dot
```

The benchmark graph groups items by status, category, score reason, failure
mode, citation coverage, token use, retrieval runs, fetches, query repetition,
and final-answer length. This is meant for report/PPT diagnostics: it shows
where capability breaks down instead of only reporting a pass rate.

## Why It Matters

This moves the project away from hand-picked transcripts and toward reproducible
benchmark evaluation:

- public dataset provenance is explicit;
- prompt leakage boundaries are testable;
- agent loop behavior can be inspected as topology, not only as logs;
- benchmark-level failures can be grouped by cause and cost;
- benchmark reports can include loop efficiency, evidence flow, and failure
  location diagrams.

## Current Validation

```bash
.venv/bin/python -m pytest -q \
  tests/test_kernel_v3_behavior_graph.py \
  tests/test_kernel_v3_finance_benchmark.py \
  tests/test_kernel_v3_finance_metric_intent.py
```

Result: `24 passed`.

## Remaining Work

- Run a fresh live public benchmark subset under explicit traffic budgets.
- Add claim-level scoring and evidence-support scoring for rubric-heavy tasks.
- Add report/PPT-ready graph rendering presets, including DOT-to-image assets.
