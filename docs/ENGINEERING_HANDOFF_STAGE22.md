# Stage22 Engineering Handoff

## Target Change

Stage22 is implemented as a host-side, shadow-first online canary layer. It records live replay artifacts and blackbox metrics, gates `canary_live` replies, and hydrates bounded same-thread world-coupling cues into the subject packet.

It does not add a watcher decision path, processor lane, background loop, or hidden policy mutation.

## Runtime Files Changed

- `holo_host/config.py`
  - adds `[autonomy]` Stage22 canary settings
- `holo_host/store.py`
  - adds `online_canary_traces`
  - records latency buckets, verdicts, selected and returned actions, artifact paths, and compact trace metadata
- `holo_host/mind_graph.py`
  - adds `world_coupling_signal`
  - adds same-thread read/upsert helpers for `file_artifact`, `image_summary`, `schedule_cue`, and `task_cue`
- `holo_host/memory_bridge.py`
  - hydrates max 3 same-thread world-coupling cues after Stage20 temporal hydration and before heavier recall
  - exposes `mind_packet.stage22`
- `holo_host/reply_api.py`
  - gates `/reply` after action-market selection
  - records canary artifacts and metrics
  - exposes diagnostics and `accept_stage22`
- `holo_host/cli.py`
  - adds Stage22 diagnostics and acceptance commands
- `holo_host/reply_service_parts/acceptance.py`
  - adds the Stage22 acceptance wrapper
- `holo_host/reply_service_parts/endpoints.py`
  - adds HTTP acceptance dispatch
- `tests/test_stage22_online_canary.py`
  - covers shadow capture, canary gates, replay artifacts, metrics, and world-coupling scoping

## Config Contract

Defaults:

```toml
[autonomy]
stage22_canary_mode = "shadow"
stage22_canary_whitelist_threads = []
stage22_canary_max_replies_per_thread_per_hour = 12
stage22_canary_max_replies_global_per_hour = 30
stage22_canary_artifact_capture = true
stage22_canary_artifact_root = "artifacts/canary/stage22"
stage22_canary_rollback_file = ".holo_runtime/STAGE22_CANARY_ROLLBACK"
```

`stage22_canary_whitelist_threads` falls back to the Windows helper whitelist when it is empty. If both are empty, `canary_live` blocks WeChat replies as not whitelisted.

## Gate Contract

The gate runs after MemoryBridge/action-market selection and before tool execution or generation.

- `disabled`: record nothing, preserve current behavior.
- `shadow`: record artifact + trace and return `action="silence"` with `stage22_shadow=true`.
- `canary_live`: pass only if whitelisted, rollback is clear, per-thread and global hourly rates are open, and the existing reply path/policy still permits the selected behavior.

The gate only blocks. It cannot choose a new action or set `send_allowed`.

## Tables

`online_canary_traces` in QueueStore:

- `event_row_id`
- `channel`
- `thread_key`
- `chat_name`
- `message_id`
- `mode`
- `verdict`
- `selected_action`
- `returned_action`
- `latency_ms`
- `latency_bucket`
- `artifact_path`
- `metadata_json`
- `created_at`

`world_coupling_signal` in Mind Graph:

- `id`
- `channel`
- `thread_key`
- `chat_name`
- `cue_type`
- `summary`
- `source_ref`
- `confidence`
- `stale_after`
- `status`
- `evidence_refs_json`
- `metadata_json`
- `created_at`
- `updated_at`

## Diagnostics

```bash
python -m holo_host show-online-canary
python -m holo_host show-blackbox-metrics --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-canary-decision --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "still here?"
python -m holo_host set-canary-rollback --enabled true --reason manual_hold
python -m holo_host replay-live-artifacts --since-hours 24
python -m holo_host show-world-coupling --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Acceptance Command

```bash
python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Tests

```bash
pytest -q tests/test_stage22_online_canary.py tests/test_stage21_policy_sedimentation.py tests/test_stage20_temporal_commitments.py
pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py
```

## Contracts To Preserve

- QueueStore telemetry is operational data, not Mind Graph self-memory.
- Mind Graph world-coupling cues are bounded perception inputs only.
- Stage22 does not add live self-modification; Stage21 replay remains the behavior-stabilization path.
- Watcher remains transport only.
- Processor fabric, action market, hard policy, initiative whitelist, and cooldowns stay final.

## Done State

Stage22 is done when shadow captures canary artifacts, metrics remain inspectable, `canary_live` is gate-bound and reversible, live artifacts can feed Stage14 replay, bounded world-coupling cues hydrate same-thread continuity, and Stage21/Stage14/Stage15 regressions remain green.
