# Stage26 Bounded Task-World State

## Goal

Stage26 broadens Holo from a chat-thread subject into a bounded task-world subject. The runtime now persists inspectable task-world objects and reuses them on same-thread ingress before heavier recall, without adding a second decision layer, a new loop family, or uncontrolled autonomy.

## Boundary

- No second brain.
- No new unbounded always-on loop.
- No watcher-side decision logic.
- No automatic heavy recall from task-world state alone.
- Same-thread relevance first; cross-thread links stay explicit and inspectable.
- Stage22 canary remains host-side, transport-only, and action-market-first.

## Runtime Surfaces

Mind Graph now owns:

- `task_world_object`
- `task_world_link`

Each object exposes:

- `object_id`
- `object_type`
- `summary`
- `source_ref`
- `confidence`
- `stale_after`
- `linked_threads`
- `linked_commitments`
- `status`

Supported object families:

- `file`
- `task`
- `schedule`
- `image_summary`
- `person`

Stage22 compatibility remains:

- `world_coupling_signal` is still available as the bounded same-thread cue surface.
- `show-world-coupling` now acts as a compatibility projection over same-thread task-world visibility when Stage26 objects are present.

## Ingress Integration

Stage26 hydration runs after Stage20 temporal hydration and before Stage24 scene shaping.

It can enrich:

- `continuity_summary`
- `cache_warmth`
- `predictive_continuity.likely_reference_targets`
- `scene_state.shared_frame`
- `scene_state.salient_objects`
- `scene_state.latent_questions`
- `scene_state.response_sketch`

It does not add a new prompt section. Ordinary short-turn prompts still rely on continuity and scene lines before verbatim history.

## Write Paths

Stage26 writes only through existing seams:

- `ingest_artifact(...)` upserts bounded file/task/schedule objects
- visual ingest upserts bounded `image_summary`
- temporal commitments and resume candidates upsert bounded task/schedule objects with explicit commitment links
- direct helper upserts allow bounded `person` and future explicit task-world objects without abusing cue-only APIs

## Diagnostics

```bash
python -m holo_host show-task-world --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host trace-world-object --object-id <object_id>
python -m holo_host trace-thread-object-links --thread-key TestUser --chat-name TestUser --channel wechat
```

HTTP/service mirrors:

- `/task-world`
- `/world-object`
- `/thread-object-links`

## Acceptance

```bash
python -m holo_host --config .holo_host.example.toml accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat
```

The gate verifies:

- bounded task-world objects persist across restart
- file/task/schedule/image-summary/person families are visible
- temporal commitments link into task-world state
- same-thread ingress can use task-world state without deep recall
- explicit memory requests still escalate
- Stage22 compatibility view still works
- prompt composition remains history-light

## Required Regressions

```bash
pytest -q tests/test_stage26_task_world_state.py tests/test_stage22_online_canary.py tests/test_stage20_temporal_commitments.py tests/test_stage14_replay.py
pytest -q
python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat
```
