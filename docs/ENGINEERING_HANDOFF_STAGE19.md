# Stage19 Engineering Handoff

## Target Change

Add a bounded attention frontier that is maintained by existing stream/runtime ticks and read by packet assembly for same-thread continuity.

## Files To Touch First

- `holo_host/daemon.py`
  - reuse `attention_tick` and `continuity_audit`
  - do not add a new always-on loop name unless an existing loop is insufficient and the docs are updated first
- `holo_host/mind_graph.py`
  - persist and expire bounded frontier entries
  - expose diagnostic state
- `holo_host/memory_bridge.py`
  - add `mind_packet.stage19`
  - apply same-thread frontier hints to recall ordering or active-state warmth
- `holo_host/reply_api.py`
  - add `accept_stage19`
  - expose `/accept-stage19`
- `holo_host/cli.py`
  - add `accept-stage19`
- `holo_host/reply_service_parts/acceptance.py`
  - add acceptance wrapper

## Tests To Add

- `tests/test_stage19_attention_frontier.py`

Minimum cases:

- frontier entry is created from existing loop tick input
- max entry count is enforced
- expired entries are discarded
- frontier is thread-scoped and canonicalized
- packet sees same-thread frontier state
- packet does not see another thread's frontier state
- initiative queue is unchanged by frontier refresh
- Stage18 prediction still works without frontier

## Acceptance Command

```bash
python -m holo_host --config .holo_host.example.toml accept-stage19 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

Expected supporting checks:

```bash
pytest -q tests/test_stage19_attention_frontier.py
pytest -q tests/test_stage18_dual_speed_reflex.py tests/test_stage17_realtime_runtime.py
python -m holo_host --config .holo_host.example.toml show-stream-status
pytest -q
```

## Contracts To Preserve

- The frontier is not a second brain.
- The frontier does not create send jobs.
- The frontier stores compact refs and one open line, not raw chat history.
- The frontier is bounded by count and expiry.
- Watcher/transport remains eyes and hands only.
- Action-market-first deliberation remains the only decision path.

## Implementation Notes

Prefer extending `MindGraph.record_stream_run()` influence or the existing continuity audit path so the frontier is causally tied to existing stream runs.

Expose enough diagnostics to answer:

- how many entries are live
- which loop last updated the frontier
- which evidence refs made a thread warm
- whether a packet used or ignored the frontier

Do not make frontier warmth equivalent to initiative permission. Initiative remains governed by existing whitelist, cooldown, policy, and adaptive gate logic.

## Done State

Stage19 is done when Holo can keep a bounded, expiring continuity frontier warm across idle gaps and use it only as same-thread packet context.
