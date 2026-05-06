# Stage19 Engineering Handoff

## Target Change

Stage19 is implemented as a bounded Mind Graph attention frontier.

It keeps same-thread continuity warm between turns by reusing existing stream writes only:

- `maintenance_stream`
- `association_stream`
- `social_stream`
- `deep_dream_cycle`

No new always-on loop, second brain, transport-side decision path, or proactive send right is introduced.

## Runtime Contracts

- `attention_frontier` is keyed by `(channel, canonical_thread_key)`.
- Entries carry compact continuity metadata only: heat, wake reason, anticipated next turn, open-loop count, reentry priority, stale time, and last stream touch.
- Entries are bounded to 8 and expose at most 3 evidence refs.
- Expired entries are visible to diagnostics but ignored by ingress hydration.
- Hydration happens in `MemoryBridge.sidecar_packet()` before heavy recall paths.
- Hydration may keep a short same-thread turn on the active/reflex path.
- Explicit memory/history/factual/search/visual turns still escalate.
- Stage18 `_select_reply_lane()` remains the only place `micro_fast` can be chosen for generation.

## Touched Surfaces

- `holo_host/mind_graph.py`
  - persistent `attention_frontier` table
  - frontier upsert from stream influence
  - `attention_frontier`, `attention_frontier_item`, `trace_wake_reasons`, `thread_warmth`
- `holo_host/memory_bridge.py`
  - one-row frontier hydration on ingress
  - `mind_packet.stage19`
  - per-thread activation warmth from frontier stream updates
- `holo_host/reply_api.py`
  - `show_attention_frontier`
  - `trace_wake_reasons`
  - `show_thread_warmth`
  - `accept_stage19`
- `holo_host/cli.py`
  - `show-attention-frontier`
  - `trace-wake-reasons`
  - `show-thread-warmth`
  - `accept-stage19`

## Acceptance Command

```bash
python -m holo_host --config .holo_host.example.toml accept-stage19 --thread-key TestUser --chat-name TestUser --channel wechat
```

Expected supporting checks:

```bash
pytest -q tests/test_stage19_attention_frontier.py tests/test_stage18_dual_speed_reflex.py tests/test_stage17_realtime_runtime.py tests/test_processor_fabric.py
pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py tests/test_stage16_release.py
python -m holo_host --config .holo_host.example.toml accept-stage18 --thread-key TestUser --chat-name TestUser --channel wechat
```

## Regression Risks

- Do not route frontier through watcher logic.
- Do not let frontier warmth skip action-market selection.
- Do not let stale frontier rows keep a thread warm.
- Do not let stream influence schedule initiative directly.
- Do not add new processor lane names.
- Do not add raw recent-history blocks to fast/reflex prompts.

## Done State

Stage19 is done when Holo has an inspectable bounded attention frontier, warm same-thread reentry remains lightweight, explicit memory queries still escalate, Stage18 remains green, and `accept-stage19` passes.
