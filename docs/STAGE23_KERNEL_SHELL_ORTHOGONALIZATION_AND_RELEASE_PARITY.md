# Stage23 Kernel Shell Orthogonalization And Release Parity

## Goal

Stage23 separates Stage22 online canary delivery effects from the core semantic reply contract. The subject runtime keeps returning the real semantic action, while Stage22 continues to express host-side suppression through transport-facing fields and canary traces.

This stage also restores release parity by fixing artifact-ingest compatibility drift and replay metric rounding drift.

## Boundary

- No new subject features.
- No new loop family.
- No canary send-right expansion.
- No second brain.
- No transport-side decision logic.
- No change to canonical `wechat:<name>` identity.

## Result Contract

Every `handle_reply()` result now carries:

- `semantic_action`
- `semantic_reason`
- `delivery_verdict`
- `delivery_send_allowed`
- `delivery_suppressed_by_canary`
- `returned_action`

Compatibility rules:

- top-level `action` and `reason` remain semantic aliases
- `returned_action` is the transport-facing realized outcome
- Stage22 suppression can change `returned_action`, but it does not rewrite `action` or `reason`

Delivery semantics:

- unsuppressed reply: `action="reply"`, `returned_action="reply"`
- unsuppressed defer: `action="defer_reply"`, `returned_action="defer_reply"`
- semantic silence: `action="silence"`, `returned_action="silence"`, `delivery_verdict="not_applicable"`
- canary-suppressed reply or defer: semantic fields stay intact and `returned_action="silence"`

## Runtime Changes

- `holo_host/reply_api.py`
  - keeps semantic reply results intact under Stage22 shadow/canary suppression
  - records delivery-layer fields in returned payloads, canary traces, and live artifacts
  - restores backward-compatible artifact ingest for older/fake memory backends
  - adds `accept-stage23`
- `holo_host/stage14_replay.py`
  - keeps rounded display metrics stable
  - exposes and aggregates raw prediction errors and raw replay metrics for gating
- `holo_host/mind_graph.py`
  - exposes raw prediction error alongside rounded prediction error in calibration traces
- `holo_host/mind_graph_parts/policy_sedimentation.py`
  - uses raw replay metrics for replay approval gates, with rounded metrics remaining reporting-only
- `holo_host/reply_service_parts/acceptance.py`
  - adds Stage23 acceptance wrapper
- `holo_host/reply_service_parts/endpoints.py`
  - adds `/accept-stage23`
- `holo_host/cli.py`
  - adds `accept-stage23`

## Stage22 Compatibility

Stage22 remains implemented and live.

What changed:

- shadow mode still suppresses delivery
- canary traces, artifact capture, rate limits, rollback switch, and live-artifact replay still work
- `online_canary_traces.returned_action` remains the transport-facing field

What no longer happens:

- shadow mode no longer rewrites semantic `action="silence"` for delivery-capable actions

## Replay Discipline

Stage23 makes replay gating raw-first:

- `aggregate_metrics` are stable display-rounded values
- `raw_aggregate_metrics` are the gating values
- Stage21 replay approval and Stage23 parity acceptance read raw metrics first and only fall back to rounded metrics for backward compatibility

## Acceptance

Commands:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key TestUser --chat-name TestUser --channel wechat
pytest -q
```

Stage23 is done when:

- `pytest -q` is green
- `accept-stage22` remains green
- `accept-stage23` is green
- reply-service tests see semantic actions under default shadow mode
- artifact ingest remains compatible with legacy/fake memory backends
- replay metrics are deterministic and raw-vs-display consistent
