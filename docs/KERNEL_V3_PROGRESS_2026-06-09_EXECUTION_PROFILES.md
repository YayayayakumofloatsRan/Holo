# Kernel v3 Progress: Execution Profiles

Date: 2026-06-09

## Problem

Public Finance Agent Benchmark runs exposed a structural issue: simple or
bounded questions could still enter the same heavy resident loop used for long
missions. That made one benchmark item pay for chat routing, semantic intake,
workmethod framing, mission assessment, repeated retrieval/evaluation, and large
context packets.

The target architecture is not one loop for every task. Kernel v3 should keep
the same host-owned journal, policy, evidence, and memory substrate while
choosing a fit-for-purpose execution lane.

## What Changed

Added `ExecutionProfile` presets:

- `local-retrieval-fast`
- `finance-fact-fast`
- `finance-modeling`
- `web-research`
- `long-mission`

`bench finance` now accepts:

```bash
--execution-profile finance-fact-fast
--mission auto|on|off
```

The benchmark default is `finance-fact-fast`. This disables resident mission
wrapping and workmethod framing for fast benchmark questions, while preserving
model planning, host policy validation, tool execution, journal records,
evidence/citation handling, and synthesis.

Fast execution profiles now treat `agent_loop` limits as hard caps. A model
planner in `retrieval_answer` mode no longer expands `finance-fact-fast` from
4 steps / 3 tool calls into the long-mission dynamic budget. The long-mission
profile keeps the large dynamic loop for genuinely resident work.

`processor_budget` is also enforced by `ProcessorFabric` before provider calls.
Budgets can cap prompt characters per call, total model calls per task, and
accumulated model tokens per task. Budget blocks return structured
`processor_budget_exceeded` processor results and are journaled like other
processor failures; they are no longer passive metadata.

`long-mission` keeps the full resident mission path for complex tasks that are
supposed to exercise multi-iteration supervision.

## Why It Matters

This is the first explicit "multi-speed gearbox" in Kernel v3:

- simple tasks can take a short path;
- finance fact tasks can use compact evidence-first execution;
- complex research and resident work can still use mission/workmethod memory and
  reflection;
- benchmark scoring can measure speed, token use, retrieval runs, and pass rate
  without forcing every question through the heaviest architecture.

## Validation

```bash
.venv/bin/python -m pytest -q \
  tests/test_kernel_v3_execution_profile.py \
  tests/test_kernel_v3_finance_benchmark.py \
  tests/test_kernel_v3_finance_benchmark_report.py
```

Result: `24 passed`.

Latest regression after hard-budget enforcement:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3*.py
```

Result: `813 passed`.

## Finance Substrate Follow-up

Implemented after the execution-profile hard caps:

- `kernel_v3/finance/` now contains finance contracts, a fact ledger, a
  Decimal calculator, and a deterministic numeric verifier.
- `calculator.compute` is exposed as a host tool for finance retrieval lanes
  that require numeric verification.
- Finance finalization journals `finance_fact_ledger` and
  `finance_numeric_verification`; unsupported material answer numbers now return
  `finance_numeric_verification_failed` instead of an unverified final answer.
- `bench finance-import --benchmark finance_agent_v2_public` normalizes the Vals
  Finance Agent v2 public text set into local Holo benchmark JSONL.

## Finance Substrate Metrics and Dev10

Follow-up work now promotes finance substrate behavior into benchmark
diagnostics:

- `trace_metrics()` records `calculator_call_count`, `formula_trace_count`,
  `finance_fact_count`, `numeric_verifier_status`,
  `answer_numeric_support_rate`, source hosts/URIs, and finance source forms.
- `FinanceBenchmarkSummary`, `bench finance-report`, `bench finance-graph`, and
  progress stderr lines surface calculator usage, formula traces, fact counts,
  numeric verifier pass rate, answer numeric support rate, and finance numeric
  failure reasons.
- `--dev-gold` adds post-run dev annotation scoring for behavior, numeric, and
  substrate expectations. Gold annotations are scoring-only and are never sent
  to model prompts.
- `data/bench/finance/fabv2_dev10.jsonl` and
  `data/bench/finance/fabv2_dev10.gold.jsonl` provide a small FAB v2-style
  development slice covering inventory efficiency, adjusted EBITDA bridge,
  transaction multiples, DCF/LBO, coverage, EV/EBITDA, MLR rebate, and purchase
  price allocation.

The numeric verifier taxonomy now distinguishes:

- `unsupported_answer_number`
- `missing_fact_ledger`
- `missing_formula_trace`
- `unit_mismatch`
- `period_mismatch`
- `assumption_not_labeled`
- `ledger_extraction_gap`

`FinanceFormulaPlanner` v1 binds fact-ledger entries to common analyst formulas
and compiles `calculator.compute` payloads when enough facts exist. It currently
supports CAGR, DIO, margin, basis-point differences, EV/Revenue, YoY growth, and
bridge subtotals. Missing inputs are journaled as diagnostics for the next loop
instead of being guessed.

Remaining work:

- Run live FAB v2 dev10 with finance-fact-fast and classify failures into
  correct verifier blocks, ledger extraction misses, and policy misses.
- Add per-item process timeout/failure row support for public live benchmark
  batches.
