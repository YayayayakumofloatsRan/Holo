# Stage26 Engineering Handoff

## Target Change

Stage26 is implemented as bounded task-world state. The runtime now persists explicit task-world objects and links, hydrates same-thread ingress from them before heavier recall, and keeps Stage22 `world_coupling_signal` as a compatibility projection instead of the primary store.

## Runtime Files Changed

- `holo_host/mind_graph.py`
  - adds `task_world_object`
  - adds `task_world_link`
  - adds bounded object/link upsert and trace helpers
  - keeps `show_world_coupling()` as a compatibility view over same-thread task-world objects when available
- `holo_host/mind_graph_parts/temporal_state.py`
  - links commitments and resume candidates into bounded task/schedule task-world objects
- `holo_host/memory_bridge.py`
  - adds Stage26 hydration after Stage20 and before Stage24
  - adds `mind_packet.stage26`
  - adds task-world diagnostics and direct object upsert helper
  - updates artifact and visual ingest paths to upsert task-world objects
- `holo_host/reply_api.py`
  - adds Stage26 diagnostics and `accept-stage26`
- `holo_host/cli.py`
  - adds `show-task-world`
  - adds `trace-world-object`
  - adds `trace-thread-object-links`
  - adds `accept-stage26`
- `holo_host/reply_service_parts/acceptance.py`
  - adds the Stage26 acceptance wrapper
- `holo_host/reply_service_parts/endpoints.py`
  - adds `/accept-stage26`

## Runtime Contract

Task-world objects expose:

- `object_id`
- `object_type`
- `summary`
- `source_ref`
- `confidence`
- `stale_after`
- `linked_threads`
- `linked_commitments`
- `status`

Supported families:

- `file`
- `task`
- `schedule`
- `image_summary`
- `person`

`mind_packet.stage26` exposes a bounded same-thread slice:

- `task_world_visible`
- `task_world_used_for_thread`
- `object_ids`
- `object_types`
- `summary`
- `linked_commitments`
- `cross_thread_links_visible`
- `hard_gate_preserved`

## Diagnostics

```bash
python -m holo_host show-task-world --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-world-object --object-id <object_id>
python -m holo_host trace-thread-object-links --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host accept-stage26 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Contracts To Preserve

- Task-world state is bounded, inspectable, and same-thread-first.
- Cross-thread coupling remains explicit in links and does not become implicit prompt visibility.
- Task-world hydration does not trigger heavy recall by itself.
- Stage22 canary remains transport-only and action-market-first.
- Stage24 scene state and Stage25 dense continuity remain bounded and intact.

## Done State

Stage26 is done when task-world objects persist across restart, same-thread reentry can use them without deep recall, temporal commitments can link into them explicitly, Stage22 compatibility views still work, and Stage14/20/22/full-suite regressions remain green.
