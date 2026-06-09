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

Benchmark reports render the same result file into project-ready Markdown,
HTML, or JSON:

```bash
holo-v3 bench finance-report \
  --results artifacts/finance_bench_results.jsonl \
  --output finance_bench_report.md
```

The report includes score summary, status counts, failure modes, score reasons,
weak-item table, and recommended next experiments. It is designed for the course
project narrative: every headline metric remains tied to the exact benchmark
result JSONL.

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
  tests/test_kernel_v3_finance_benchmark_report.py \
  tests/test_kernel_v3_behavior_graph.py \
  tests/test_kernel_v3_finance_benchmark.py \
  tests/test_kernel_v3_finance_metric_intent.py
```

Result: `28 passed`.

## Current Live Benchmark Snapshot

The current complete local live run is:

```text
.state/kernel_v3/bench/finance/run_kernelv3_live_0609_full40_v1.jsonl
```

Confirmed summary:

- items: 40
- scored: 40
- passed: 28
- failed: 12
- pass rate: 70.0%
- citation-present rate: 85.0%
- numeric accuracy: 66.7%
- average retrieval runs: 4.875
- average query repetition: 18.4%
- average final answer length: 1,801 chars

Generated review artifacts:

```text
.state/kernel_v3/bench/finance/run_kernelv3_live_0609_full40_v1.report.md
.state/kernel_v3/bench/finance/run_kernelv3_live_0609_full40_v1.dot
```

A fresh 2026-06-09 one-item live fast run was attempted with strict traffic
budgets but timed out after five minutes before producing an item result. This
is now a live benchmark finding: the single-item path needs latency work before
it is suitable for fast iteration.

## Remaining Work

- Run a fresh live public benchmark subset under explicit traffic budgets.
- Add claim-level scoring and evidence-support scoring for rubric-heavy tasks.
- Reduce live single-item benchmark latency while preserving evidence quality.
- Add report/PPT-ready graph rendering presets, including DOT-to-image assets.
