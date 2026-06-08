# Kernel v3 Progress: Memory Digest and SEC Extraction

Date: 2026-06-08

## Problem Observed

A live finance task exposed a serious retrieval-quality issue:

- Holo fetched SEC `companyfacts` JSON for Apple.
- The agent loop kept searching for net income and official financial
  statement evidence.
- The final answer cited scattered old revenue facts instead of using the
  latest structured annual metrics already present in the artifact.

The loop was running, but the tool/evidence boundary was weak. The host had an
official structured payload, yet extraction projected it as isolated lines.
Planner/evaluator packets then saw incomplete evidence and repeated the same
class of retrieval action.

## Fix: SEC Companyfacts Annual Summary Rows

`kernel_v3/retrieval/extract.py` now projects SEC companyfacts JSON into compact
annual summary rows before ordinary metric rows.

The summary rows:

- group facts by fiscal year and period end;
- prefer annual forms such as `10-K`, `20-F`, and `40-F`;
- include metrics such as revenue, net income, operating income, cash flow,
  assets, liabilities, shareholders equity, and diluted EPS when present;
- preserve concept, metric, value, unit, FY/FP, form, filed date, period end,
  and accession number;
- remain bounded readable projections while raw JSON stays in ArtifactStore.

This is a generic SEC XBRL adapter improvement, not an AAPL-specific fixture.
Any companyfacts payload with the same SEC structure benefits from it.

## Fix: Finance Metric Coverage and Evidence Compaction

The finance profile now treats EPS / earnings per share as a first-class
financial facet when the user goal or model plan asks for it. The evidence
compaction layer also ranks structured annual summary rows and concrete
requested metric coverage ahead of newer but irrelevant balance-sheet noise.

This keeps the host contract general:

- the model still decides the research goal and retrieval payload;
- the host validates and extracts structured facts from official payloads;
- evidence selection favors requested facets such as revenue, net income, and
  EPS instead of any line that happens to contain a number;
- broad finance tasks are not forced to require net income or EPS unless the
  goal/plan/query asks for them.

## Fix: Thread Learning Digest Proposals

Memory now has a host-side consolidation hook:

- non-blocking task-reflection and research-result proposals can be combined
  into a `thread_learning_digest` proposal;
- digest proposals keep `source_proposal_ids` and `source_proposal_count` for
  auditability;
- they remain pending proposals and are not committed durable memory;
- chat memory admin previews expose whether a proposal is non-blocking and
  which source proposals it summarizes.

`AgentRuntime` calls this digest hook after meaningful research-result or
failure-learning proposals. The goal is to reduce scattered thread-learning
noise in later planner packets without weakening the durable-memory approval
boundary.

## Fix: Final Answer Quality Repair Loop

Finance and other research answers now have a stronger host-side quality
contract:

- finance, academic, and policy research reports default to a strict answer
  quality gate when the task resolves to a detailed/deep report;
- final-answer quality checks verify length, section count, evidence refs,
  citation refs, target coverage, and source-quality discussion;
- if a model synthesizer produces a low-quality final answer, `AgentRuntime`
  does not immediately finalize or silently fail. It sends a structured
  `retry_instruction` with the concrete quality gaps back to
  `synthesizer.answer` for one repair pass;
- the repaired answer is checked by the same host gate. If it still fails, the
  task returns `final_answer_quality_insufficient` and records a non-blocking
  task-reflection memory proposal;
- fake/offline synthesizer paths are not forced to write professional reports;
  they remain contract tests for host boundaries. Live/model paths carry the
  strict quality behavior.

This makes the loop closer to the project proposal target: the model remains
the semantic writer, while the host refuses to treat "some citation exists" as
professional completion.

## Fix: Quality Checks Enter Thread Working Memory

`ThreadWorkingMemoryProvider` and `collect_run_delta()` now carry compact
`final_answer_quality_check` records:

- mission and workmethod assessors can see whether a previous final answer
  failed quality checks;
- later planner/evaluator packets get an `answer_quality_gap` attention block
  instead of only a generic failure report;
- quality-check context is compact: refs, pass/fail, attempt, gaps, answer
  length, profile format/domain. Raw answers and raw artifacts stay in journal
  and ArtifactStore.

This improves Holo's self-iteration path without allowing models to write
durable memory directly.

## Fix: Planner Provider Failure Is Not User Input

When `planner.propose` fails because the processor provider fails, the fallback
action is now a diagnostic `respond` action rather than `ask_user`. The
top-level `AgentRuntime` still returns a `model_planner_processor_failed`
failure report, but chat threads no longer get stuck in a fake pending
question such as "Planner could not produce a safe action".

## Validation

Targeted regression:

```bash
.venv/bin/python -m pytest -q \
  tests/test_kernel_v3_phase98_sec_edgar_provider.py \
  tests/test_kernel_v3_phase96_retrieval_html_extraction.py \
  tests/test_kernel_v3_phase82_research_source_policy.py \
  tests/test_kernel_v3_phase108_generic_research_profile_policy.py
```

Result:

```text
47 passed
```

Full kernel-v3 regression:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_*.py
```

Result:

```text
757 passed
```

Live smoke:

```bash
HOLO_V3_LIVE_MODEL=1 ./holo-v3 chat --thread smoke-0608-aapl-sec-after-fix \
  --once "请使用SEC companyfacts或官方财报查询 Apple Inc. / AAPL 的最新完整财年收入、净利润和EPS，并用中文简要说明证据来源和局限。" \
  --online --planner model --evaluator model --synthesizer model \
  --semantic-intake model --turn-router model \
  --research-profile finance_fundamentals --research-depth deep \
  --live-retrieval --live-search-strategy adaptive --no-color
```

Observed result:

```text
completed task=task-27
final answer cited SEC companyfacts evidence for revenue and net income;
EPS was cited from available SEC companyfacts evidence with an explicit
freshness limitation when the latest-year EPS was not present in selected
evidence.
```

Current live smoke after the quality-gate repair was attempted with the same
DeepSeek/live retrieval route, but the provider returned:

```text
deepseek HTTP 402: Insufficient Balance
```

That did not validate model behavior. It did validate the host diagnosis path:
the failure was classified as `model_planner_processor_failed`, with
`latest_processor_error` showing the 402 provider error and retrieval capability
still reported as available. After this pass, provider failure is no longer
represented as a user clarification request.

## Remaining Work

This pass fixes one important tool boundary, but finance research still needs:

- richer XBRL concept mapping and normalized statement tables;
- source-specific extraction for primary SEC filing HTML;
- better market-data acquisition for valuation metrics;
- mission/subgoal coverage convergence so a sufficient SEC evidence report does
  not trigger avoidable extra retrieval loops;
- live benchmark reporting after each finance task so regressions are visible.
