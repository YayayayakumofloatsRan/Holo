# Stage24 Engineering Handoff

## Implemented Change

Stage24 adds a bounded, inspectable `scene_state` layer on top of Stage18 predictive continuity.

The live rule is:

- ordinary short turns can use compact scene state before verbatim history
- scene state is same-thread, bounded, and inspectable
- action-market selection still happens before language generation

## Runtime Surfaces

- `holo_host/mind_graph.py`
  - persists `scene_state_json` inside `active_thread_state`
  - adds bounded scene normalization, reduction, and migration
  - records reducer metadata under `metadata.stage24_scene`
- `holo_host/memory_bridge.py`
  - hydrates scene state into packets
  - exposes `mind_packet.stage24`
  - adds scene diagnostics and scene-aware action-market overlay wiring
- `holo_host/policy_runtime/action_market.py`
  - adds bounded `scene_delta` and `scene_rationale` overlays
- `holo_host/processors.py`
  - updates fast-path prompt ordering to place scene state before optional verbatim history
- `holo_host/reply_api.py`
  - adds scene diagnostics and `accept_stage24`
  - adds optional off-hot-path processor compression hints with deterministic fallback
- `holo_host/reply_service_parts/acceptance.py`
  - adds Stage24 acceptance wrapper
- `holo_host/reply_service_parts/endpoints.py`
  - adds `/accept-stage24`
- `holo_host/cli.py`
  - adds `show-scene-state`
  - adds `trace-predicted-branches`
  - adds `trace-scene-compression`
  - adds `accept-stage24`

## Data Contract

`active_thread_state.scene_state` includes:

- `shared_frame`
- `topic_stack`
- `salient_objects`
- `latent_questions`
- `predicted_branches`
- `relationship_trajectory`
- `response_sketch`
- `scene_confidence`
- `freshness_at`

`mind_packet.stage24` exposes the inspectable packet summary:

- visibility flag
- shared frame
- topic stack
- predicted branches
- relationship trajectory
- response sketch
- confidence
- freshness
- compression mode and reason

## Prompt And Routing Contract

For the ordinary active-thread fast path, prompt ordering is:

1. continuity summary
2. scene state
3. scene next
4. last outbound action
5. predictive continuity
6. optional one-line last exchange

This keeps Stage17 fast-lane behavior bounded while making continuity richer than a single predictive hint.

## Diagnostics And Acceptance

Commands:

```bash
python -m holo_host show-scene-state --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-predicted-branches --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-scene-compression --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

Expected pass checks:

- Stage23 acceptance green
- scene fields visible
- scene state persisted
- ordinary short turn uses scene before history
- explicit memory query still escalates
- action-market scene overlay visible
- scene diagnostics visible
- outbound scene update persists

## Regression Commands

```bash
pytest -q tests/test_stage24_scene_state.py tests/test_stage17_realtime_runtime.py tests/test_stage22_online_canary.py tests/test_stage14_replay.py
pytest -q
python -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Contracts To Preserve

- Do not let scene state become a second brain or hidden planner.
- Do not add a new always-on loop.
- Do not let scene state trigger sends, recalls, or tool use by itself.
- Do not regress explicit memory/history/factual/search/visual escalation.
- Do not widen Stage22 canary send rights.
- Do not change canonical `wechat:<name>` identity handling.

## Next Stage

Stage25 should couple artifacts, tool outcomes, deferred replies, and world cues into the same bounded scene-state surface.

Bounded subject programs are explicitly deferred until a later re-plan.
