# Kernel v3 Progress: Strategy Supervision and Safety Boundary

Date: 2026-06-05

## Purpose

This pass hardens the agent loop where earlier live runs exposed the same
failure pattern: a model could correctly explain that it should switch search
strategy, but the concrete `retrieval.run` payload still repeated the failed
query or source surface. The fix keeps the LLM as the semantic decision source
while adding host-owned validation that checks whether the action packet really
advances the mission.

This is not a case table. The host checks generic search-state properties:
query novelty, attempted strategy, source family, direct source URL, structured
provider metadata, and mission-level missing requirements.

## Changes

- Added `kernel_v3.retrieval.strategy` with a small, pure strategy supervisor.
  It normalizes query signatures, detects materially repeated retrieval
  payloads, and can rewrite bounded search fields to use diversified query
  batches, source-family switches, or structured/direct-source candidates from
  prior diagnostics.
- Connected mission directives into planner-visible `agent_replan_hints`.
  Mission-level `avoid_repeating`, `strategy`, and `missing_requirements` now
  become hard context for the next planner packet instead of passive prose.
- Connected the strategy supervisor inside model action binding. The model still
  proposes `retrieval.run`; the host applies recipe defaults, profile defaults,
  mission hints, and payload supervision before PolicyGate and tool execution.
- Improved SEC companyfacts readable extraction so financial facts expose
  `period=annual|quarterly|period`, prefer annual filing facts for annual or
  fundamental queries, and preserve recent quarterly facts for current-period
  coverage.
- Fixed `kernel_v3.memory` package imports so memory-store/context imports no
  longer eagerly import the memory recall operator and create an import cycle.
- Added resident queue cancellation and `holo-v3 resident cancel <message_id>`.
  Cancelled inbox messages clear leases/retry timers and are not claimed by
  workers.
- Added a processor fabric boundary for private context. External model
  providers do not receive secret-like prompts, sensitive durable-memory
  sections, or private-context markers unless the host explicitly sets
  `allow_private_context_to_external_model`.
- Tightened system capability ABI validation after a live smoke exposed an
  over-eager model packet. `system.time` is now accepted only from the canonical
  `system_time` intent; generic `system_answer`, self-description, and system
  capability checks are downgraded to semantic/direct answers even if the model
  incorrectly attaches `system.time`.

## Verification

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase112_strategy_supervision.py \
  tests/test_kernel_v3_phase5_semantic_processors.py \
  tests/test_kernel_v3_phase72_memory_context_admin.py \
  tests/test_kernel_v3_phase110_active_memory_recall.py
```

Result: `69 passed`.

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase103_model_retrieval_feedback.py \
  tests/test_kernel_v3_phase105_adaptive_search_strategy.py \
  tests/test_kernel_v3_phase106_fred_structured_provider.py \
  tests/test_kernel_v3_phase107_fiscaldata_structured_provider.py \
  tests/test_kernel_v3_phase112_strategy_supervision.py
```

Result: `26 passed`.

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase*.py
```

Result: `662 passed`.

Live smoke, isolated under `/tmp/holo-v3-live-smoke-3`, sent a public one-line
capability-check prompt through DeepSeek V4 Flash. Result: completed in one run,
no `system.time` call, final visible answer returned to the user.

Live retrieval smoke, isolated under `/tmp/holo-v3-live-retrieval-smoke-bing`,
queried public DeepSeek API documentation terms with `bing_html,duckduckgo_html`
and live HTTP fetch enabled. Result: one search attempt, three fetch attempts,
two evidence items, two citation refs, final retrieval report `sufficient`.
Single-engine `duckduckgo_html` returned zero sources in the same environment,
so operational live retrieval should prefer multi-engine search or source
directory/structured providers rather than relying on one HTML engine.

## Remaining Work

- Retrieval still needs a stronger generic search operator: query
  diversification, direct URL fetch, source-family selection, and extraction are
  now better coupled, but the provider layer still needs deeper source discovery
  and parallel search orchestration.
- Memory is safer and visible to the loop, but long-running active working
  memory, automatic post-task distillation, and resident self-review remain
  future work.
- Private-context live model use now has a hard boundary, but a full
  authorization gateway and local-model route are still needed before Holo can
  safely process private workspace or memory content with external providers.
