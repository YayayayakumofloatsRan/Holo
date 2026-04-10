# Stage20 Temporal Commitments And Interruption Recovery

## Goal

Stage20 gives Holo durable temporal continuity without increasing autonomous send rights. Open loops, commitments, deferred intentions, interruption markers, resume candidates, and due followup keys now survive processor turns, daemon cycles, and runtime restarts.

The implemented split is:

- `QueueStore.jobs` remains the timing/job surface.
- Mind Graph `temporal_subject_state` stores subject meaning and recovery state.
- Ingress hydration and the action market decide how a due item influences the next reply path.

## Boundary

- No scheduler-brain.
- No new unbounded loop.
- No new processor lane.
- No transport-side decision logic.
- No proactive send bypass.
- No raw recent-history block in temporal state.
- No commitment without an event/action ref or compact evidence metadata.
- Owner shutdown, policy gates, cooldowns, and manual review remain final.
- Preserve action-market-first deliberation.

## Runtime Surfaces

Mind Graph owns one bounded table:

- `temporal_subject_state`
- unique key: `(channel, thread_key, dedupe_key, type)`
- live statuses: `open`, `scheduled`, `due`
- terminal statuses: `fulfilled`, `superseded`, `canceled`, `expired`
- hard bounds: max 48 retained items per thread surface and max 24 rows touched by one status transition

Required item fields:

- `type`
- `channel`
- `thread_key`
- `chat_name`
- `confidence`
- `source_event_id`
- `source_action_ref`
- `source_action_type`
- `due_at`
- `revisit_after`
- `revisit_before`
- `resume_cue`
- `dedupe_key`
- `status`
- `queue_job_id`
- `metadata_json`
- `created_at`
- `updated_at`

Grouped read surfaces:

- `open_loops`
- `commitments`
- `deferred_intentions`
- `interruption_markers`
- `resume_candidates`
- `due_followup_keys`

Public helpers:

- `MindGraph.upsert_temporal_item(...)`
- `MindGraph.update_temporal_item_status(...)`
- `MindGraph.close_temporal_items(...)`
- `MindGraph.temporal_state(...)`
- `MindGraph.show_open_loops(...)`
- `MindGraph.show_commitments(...)`
- `MindGraph.trace_resume_candidate(...)`
- matching `MemoryBridge` and service wrappers

## Reducers

Implemented creation/update paths:

- inbound active-thread reentry cues such as "we were talking about..." create bounded `open_loop` and `resume_candidate` rows
- selected `defer_reply` creates one `deferred_intention`, one linked `commitment`, and one deduped `deferred_reply` queue job
- due resume/interruption rows can bias reply recovery through action-market candidate metadata
- speech outcomes close matching live temporal rows by `source_event_id` or `source_action_ref`
- terminal rows remain inspectable with `include_inactive=True` and are ignored for reply-path resumption

Queue dedupe is deterministic:

- `deferred_reply` payloads carry `dedupe_key`
- `QueueStore.find_pending_job_by_dedupe_key(...)` prevents duplicate pending/retry/running jobs
- stale inbound proactive followups use a stable followup dedupe key

## Ingress Contract

`MemoryBridge.sidecar_packet()` hydrates temporal state after Stage19 frontier hydration and before heavier recall.

Hot path properties:

- same-thread only
- one Mind Graph row-set lookup
- no vector scan by temporal state alone
- no graph recall escalation by temporal state alone
- explicit memory/history/factual/search/visual requests still win

When temporal state is live, `mind_packet.stage20` exposes:

```json
{
  "temporal_visible": true,
  "temporal_used_for_thread": true,
  "thread_key": "wechat:Nemoqi",
  "open_loops": [],
  "commitments": [],
  "deferred_intentions": [],
  "interruption_markers": [],
  "resume_candidates": [],
  "due_followup_keys": [],
  "resume_candidate": {},
  "resume_cue": "",
  "commitment_due": false,
  "interruption_recovered": false,
  "duplicate_recovery_blocked": false,
  "temporal_pressure": 0.0
}
```

`active_thread_state.metadata.stage20_temporal_state` carries only compact continuity hints: `resume_cue`, `due_followup_keys`, `commitment_due`, and `temporal_pressure`.

## Action Market Contract

Temporal items never send directly.

Due/resume items add bounded metadata and scoring bias to existing action candidates:

- `reply_once`
- `defer_reply`
- `history_refresh`
- `silence`

The `temporal_context` candidate metadata carries `stage`, `due`, `resume_cue`, `due_followup_keys`, and `source_action_type`.

Stage18 generation-lane routing remains unchanged: `micro_fast` is still selected only by the existing conservative Stage18 lane rules after action selection.

## Diagnostics

```bash
python -m holo_host show-open-loops --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host show-commitments --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-resume-candidate --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

HTTP/service surfaces mirror the CLI:

- `/open-loops`
- `/commitments`
- `/resume-candidate`
- `/accept-stage20`

## Acceptance Checklist

Closure command:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage20 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The acceptance gate verifies:

- Stage19 acceptance remains green.
- Temporal state persists and returns grouped surfaces.
- `defer_reply` creates one deduped queue job plus linked commitment/deferred-intention rows.
- Due resume state enters `mind_packet.stage20` before heavy recall.
- Recovery pressure enters action-market candidate metadata.
- Interleaved WeChat threads remain isolated by canonical `wechat:<name>` keys.
- Expired rows are inspectable but ignored for active resumption.
- Explicit memory/history queries still escalate.
- Fulfilled resume rows are not reused.

Required regressions:

```bash
pytest -q tests/test_stage20_temporal_commitments.py tests/test_stage19_attention_frontier.py tests/test_stage18_dual_speed_reflex.py tests/test_stage17_realtime_runtime.py tests/test_processor_fabric.py
pytest -q tests/test_store_threading.py tests/test_stage14_replay.py tests/test_stage15_modularization.py tests/test_stage16_release.py
python -m holo_host --config .holo_host.example.toml accept-stage19 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage20 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Regression Risks

- Temporal rows cause direct sends instead of action-market bias.
- Deferred replies duplicate queue jobs after restart.
- Terminal rows continue to steer packets.
- Expired rows create stale pressure.
- Explicit memory/history/factual turns are kept on a fast temporal path.
- Thread identity splits between `wechat:<name>` and bare aliases.
- Runtime jobs become "meaning" without matching Mind Graph rows.

## Rollback

Stage20 degrades by ignoring `mind_packet.stage20` and leaving existing `QueueStore` jobs intact. Terminal temporal rows are reversible/inspectable, and the queue remains the authoritative timing surface.
