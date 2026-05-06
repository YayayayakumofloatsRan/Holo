# Engineering Handoff Stage25

## Stage
- `stage25-dense-continuity-scheduler-and-working-set`

## Intent
- Keep a bounded set of hot threads warm between turns using existing stream runs only.
- Improve reentry and interruption recovery before deeper recall.
- Preserve the Stage17/19/20/24 constraints: bounded ingress, inspectable state, no send-right changes, and no new loop family.

## Files Touched
- `holo_host/config.py`
- `holo_host/mind_graph.py`
- `holo_host/memory_bridge.py`
- `holo_host/reply_api.py`
- `holo_host/reply_service_parts/acceptance.py`
- `holo_host/reply_service_parts/endpoints.py`
- `holo_host/cli.py`
- `tests/test_stage25_dense_continuity.py`
- `tests/test_stage19_attention_frontier.py`
- `tests/test_stage20_temporal_commitments.py`

## Core Additions
- New persistent tables:
  - `dense_working_set`
  - `thread_pulse_trace`
- New CLI and service diagnostics:
  - `show-continuity-budget`
  - `show-dense-working-set`
  - `trace-thread-pulse`
- New acceptance:
  - `accept-stage25`
- New `mind_packet.stage25` slice for ingress inspection.

## Behavioral Summary
- `record_stream_run(...)` now rebuilds a bounded continuity snapshot after allowed stream runs.
- Snapshot rebuild considers only bounded local state:
  - attention frontier
  - temporal state
  - active thread and scene state
- `sidecar_packet(...)` hydrates from the dense working set before hybrid or deep recall.
- Dense continuity can revive a hot thread even after the frontier is stale and the richer active thread state has been removed.
- Explicit memory queries still bypass the fast lane and escalate normally.

## Verification
- `pytest -q tests/test_stage25_dense_continuity.py tests/test_stage19_attention_frontier.py tests/test_stage20_temporal_commitments.py tests/test_stage22_online_canary.py`
- `pytest -q`
- `python -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python -m holo_host --config .holo_host.example.toml accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat`

## Follow-On Work
- Stage26 remains the next planned milestone.
- The older Stage25 artifact/tool/outcome coupling scope is explicitly deferred and should not be mixed into Stage26 without an explicit re-plan.
