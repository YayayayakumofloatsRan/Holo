# Kernel v3 Host Situation Layer

Date: 2026-06-06

## Purpose

Holo Kernel v3 now has a unified `HostSituation` packet for host-owned state.
The goal is to reduce capability hallucination and improve autonomous recovery
after tool failures. Models should not infer whether Holo can search, fetch,
read, write, use finance research, or continue a loop from generic model
defaults. They should read the host packet.

## What Changed

- Added `kernel_v3/agent/host_situation.py`.
- Added `ContextBundle.state.host_situation` for planner/evaluator context.
- Added `FailureReport.host_situation` and journals `host_situation` records
  when the agent returns a failure report.
- Added `AgentRuntimeResult.host_situation` so mission, chat, resident, and
  post-run supervision can inspect the same state after success or failure.
- Completed, `needs_user_input`, and failed task exits now journal a terminal
  `host_situation` record. Failure reports reuse the same packet instead of
  rebuilding a divergent copy after journaling.
- `TraceRenderer.render_task()` now renders concise host situation summary
  lines for operator review: task mode, permission profile, retrieval
  availability, live search/fetch flags, budget, recent retrieval/fetch counts,
  latest retrieval status, failure diagnosis, next action, and latest redacted
  processor error preview.
- Thread-local working context and thread RAG now retain compact
  `host_situation` trace items. Follow-up turns can carry the previous loop's
  real capability state, retrieval attempt counts, failure diagnosis, and next
  possible action into semantic/planner/evaluator packets instead of forcing the
  model to infer them from scattered logs.
- Added compact processor-result summaries to `HostSituation.recent_activity`,
  including task type, provider, model, status, duration, and redacted error
  preview. This lets user-visible failure reports distinguish model/API
  connectivity or JSON/planning failures from tool/retrieval failures.
- Added ProcessorFabric provider-availability circuit breaking: after a live
  provider network/unavailable failure, later calls to the same provider in the
  same process return a journaled `provider_circuit_open` result with the
  previous redacted error preview instead of repeatedly waiting on the same
  unreachable API.
- Added `host_situation` to synthesizer payloads through retrieval/workspace
  report diagnostics.
- Added `host_situation` to chat route prompts and semantic intake runtime
  context.
- Updated processor prompts/contracts to treat `host_situation` as source of
  truth for tools, live retrieval, permissions, budgets, finance research, and
  failure attribution.
- Replaced the old generic failure sentence that said the user might need to
  allow live retrieval. Failure text now distinguishes:
  - retrieval tool/provider not configured;
  - network budget or permission unavailable;
  - tool budget exhausted after attempts;
  - citation coverage insufficient;
  - model/API processing or planning failure;
  - search/fetch/extraction/source-authority/evidence-coverage failures.

## Design Boundary

`HostSituation` is not a new decision layer. It does not execute tools, grant
permissions, write memory, or bypass `PolicyGate`. It is a redaction-safe state
packet used by existing processors and reports.

The packet includes refs, counters, provider ids, compact observations, limits,
and diagnostics. It must not include raw fetched bodies, secrets, API keys, or
private reasoning.

Trace rendering is also a public operational trace, not hidden chain of
thought. It shows host-derived facts and diagnostics only.

## Why This Matters

Recent live runs showed Holo could attempt live retrieval and still tell the
user it had no network permission or could not do finance work. That was a
host-state propagation failure. The model had evidence snippets and a failure
report, but not a single authoritative view of host capabilities and what had
already happened.

The new packet makes the following distinction explicit:

- permission/configuration failure;
- search provider quality failure;
- fetch failure;
- extraction failure;
- source authority failure;
- citation coverage failure;
- mission coverage failure.

This should reduce false self-limitations and make the agent loop more
reliable when a tool returns weak or incomplete evidence.

## Verification

Targeted regression:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase120_host_situation.py
```

Full kernel-v3 regression after terminal host-situation trace rendering:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_*.py
# 738 passed
```

Broader smoke used during implementation:

```bash
.venv/bin/python -m pytest -q \
  tests/test_kernel_v3_phase120_host_situation.py \
  tests/test_kernel_v3_phase5_semantic_processors.py \
  tests/test_kernel_v3_phase62_chat_runtime.py \
  tests/test_kernel_v3_phase6_agent_runtime.py \
  tests/test_kernel_v3_phase109_mission_supervisor.py \
  tests/test_kernel_v3_phase117_workmethod_layer.py
```

## Next Audit Points

- Live retrieval quality still needs stronger source acquisition and extraction
  coverage. HostSituation makes failures visible; it does not by itself improve
  retrieval ranking or document acquisition.
- Live model/API unavailability is now clearer and faster, but a future resident
  runtime should add explicit provider health status and recovery/backoff rather
  than keeping the circuit only in process memory.
- Mission/workmethod loops should use host_situation to force strategy shifts
  when repeated retrieval attempts have the same failure diagnosis.
- Finance reports should use the same packet to avoid claiming finance is
  unsupported while still respecting the boundary against personalized licensed
  investment advice.
