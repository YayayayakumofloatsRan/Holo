# Stage19 Bounded Background Continuity And Attention Frontier

## Goal

Stage19 turns Stage18 thread-resident subject state into bounded between-turn continuity.

The runtime now keeps an inspectable attention frontier for warm same-thread reentry. It is a compact Mind Graph index, not a second brain and not a sender.

## Scope Boundary

- No second brain layer.
- No new unbounded always-on loop.
- No new proactive send rights.
- No watcher or transport-side policy.
- No raw full-history cache in the frontier.
- No learned opaque weights.
- Preserve action-market-first deliberation.

Stage19 frontier influence is fed only by existing bounded streams:

- `maintenance_stream`
- `association_stream`
- `social_stream`
- `deep_dream_cycle`

`attention_tick`, `continuity_audit`, and other loop families are not Stage19 frontier writers.

## Runtime Surfaces

Persistent Mind Graph table:

```json
{
  "channel": "wechat",
  "canonical_thread_key": "wechat:Nemoqi",
  "thread_heat": 0.0,
  "wake_reason": "",
  "anticipated_next_turn": "",
  "pending_open_loop_count": 0,
  "reentry_priority": 0.0,
  "stale_after": "",
  "last_stream_touch_at": ""
}
```

Supporting fields may include `chat_name`, `metadata_json`, `created_at`, and `updated_at`.

Bounded defaults:

- max frontier entries: `8`
- max evidence refs per entry: `3`
- max motifs/open lines surfaced per entry: `4`
- expired entries are readable for diagnostics but ignored by ingress hydration

`mind_packet.stage19` exposes:

```json
{
  "frontier_visible": true,
  "frontier_used_for_thread": true,
  "canonical_thread_key": "wechat:Nemoqi",
  "thread_heat": 0.18,
  "thread_warmth": "cool",
  "wake_reason": "continuity",
  "anticipated_next_turn": "continuity",
  "pending_open_loop_count": 0,
  "unresolved_thread_pull": false,
  "reentry_priority": 0.23,
  "stale_after": "",
  "last_stream_touch_at": "",
  "frontier_stale": false,
  "evidence_refs": ["stream:association_stream"]
}
```

## Ingress Contract

On ingress, `MemoryBridge.sidecar_packet()` performs a same-thread `attention_frontier` row lookup before heavier recall paths.

This hydration may:

- mark active state as `frontier_warm`
- fill a compact continuity summary when active state is otherwise cold
- expose wake reason, anticipated next turn, thread warmth/coldness, and unresolved pull
- refresh deterministic predictive continuity for low-risk short turns

This hydration may not:

- perform graph/vector recall
- run stream work
- select an action
- bypass explicit memory/history/factual escalation
- broaden Stage18 `micro_fast` lane rules

## Diagnostics

```bash
python -m holo_host --config .holo_host.example.toml show-attention-frontier --channel wechat
python -m holo_host --config .holo_host.example.toml trace-wake-reasons --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml show-thread-warmth --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

HTTP surfaces:

- `GET /attention-frontier`
- `GET /wake-reasons`
- `GET /thread-warmth`

## Acceptance

Closure command:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage19 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The acceptance gate verifies:

- frontier state is persisted and inspectable
- frontier updates are caused by one of the four allowed streams
- warm short same-thread reentry can use the active/reflex path
- ordinary short ingress does not run stream work
- stale frontier entries decay to cold and are ignored by hydration
- explicit memory/history queries still escalate
- Stage18 acceptance remains green

Regression commands:

```bash
pytest -q tests/test_stage19_attention_frontier.py tests/test_stage18_dual_speed_reflex.py tests/test_stage17_realtime_runtime.py tests/test_processor_fabric.py
pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py tests/test_stage16_release.py
python -m holo_host --config .holo_host.example.toml accept-stage18 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage19 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Regression Risks

- A new background loop duplicates daemon responsibility.
- Frontier refresh scans unbounded history.
- Frontier entries leak across WeChat aliases.
- Social stream influence schedules initiative directly.
- Frontier state becomes another memory store instead of a bounded index over existing memory.
- Idle stream ticks increase ordinary live-turn latency.
- Warmth accidentally bypasses explicit recall escalation.

## Rollback

Stage19 degrades by returning an empty or stale frontier. Stage18 predictive continuity and Stage17 active-thread fast lane must still work when frontier state is absent.
