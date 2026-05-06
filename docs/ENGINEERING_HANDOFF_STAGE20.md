# Stage20 Engineering Handoff

## Target Change

Stage20 is implemented as a bounded temporal subject layer in Mind Graph. It persists open loops, commitments, deferred intentions, interruption markers, resume candidates, and due followup keys while leaving `QueueStore.jobs` as the timing surface.

## Runtime Files Changed

- `holo_host/mind_graph.py`
  - creates `temporal_subject_state`
  - exposes temporal state wrappers
  - creates explicit reentry open-loop/resume rows from active-thread inbound reducers
  - feeds due temporal commitment hints into initiative thread selection
- `holo_host/mind_graph_parts/temporal_state.py`
  - owns upsert, status update, close, prune, grouped read, and diagnostic helpers
- `holo_host/mind_graph_parts/outcome_appraisal.py`
  - closes matching live temporal rows for successful speech outcomes by event/action ref
- `holo_host/memory_bridge.py`
  - hydrates `mind_packet.stage20` after Stage19 frontier hydration and before heavier recall
  - adds compact temporal continuity to active state metadata
  - biases existing action-market candidates with bounded `temporal_context`
- `holo_host/store.py`
  - adds `find_pending_job_by_dedupe_key(...)`
  - dedupes stale inbound proactive followup jobs by stable payload key
- `holo_host/reply_api.py`
  - links `defer_reply` to one deduped queue job plus temporal `deferred_intention` and `commitment` rows
  - exposes service/HTTP diagnostics and `accept_stage20`
- `holo_host/cli.py`
  - adds `show-open-loops`, `show-commitments`, `trace-resume-candidate`, and `accept-stage20`
- `holo_host/reply_service_parts/acceptance.py`
  - adds acceptance wrapper
- `holo_host/reply_service_parts/endpoints.py`
  - adds HTTP acceptance dispatch

## Temporal Table Contract

Table: `temporal_subject_state`

Unique key:

- `(channel, thread_key, dedupe_key, type)`

Required fields:

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

Live statuses are `open`, `scheduled`, and `due`. Terminal statuses are `fulfilled`, `superseded`, `canceled`, and `expired`.

## Diagnostics

```bash
python -m holo_host show-open-loops --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host show-commitments --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host trace-resume-candidate --thread-key TestUser --chat-name TestUser --channel wechat
```

## Acceptance Command

```bash
python -m holo_host --config .holo_host.example.toml accept-stage20 --thread-key TestUser --chat-name TestUser --channel wechat
```

The gate checks persistence, grouping, deferred-reply dedupe, due resume hydration, action-market metadata, interleaved thread isolation, expired-row ignoring, explicit memory escalation, fulfilled-resume suppression, canonical WeChat identity, and Stage19 compatibility.

## Tests

```bash
pytest -q tests/test_stage20_temporal_commitments.py tests/test_stage19_attention_frontier.py tests/test_stage18_dual_speed_reflex.py tests/test_stage17_realtime_runtime.py tests/test_processor_fabric.py
pytest -q tests/test_store_threading.py tests/test_stage14_replay.py tests/test_stage15_modularization.py tests/test_stage16_release.py
```

`tests/test_stage20_temporal_commitments.py` covers:

- interleaved multi-thread isolation by canonical `wechat:<name>` keys
- `defer_reply` queue and temporal dedupe
- restart-safe open loops, commitments, resume candidates, and due keys
- day-gap followup dedupe
- explicit "we were talking about..." reentry before heavy recall
- terminal/expired rows being inspectable but ignored for resumption
- explicit memory query escalation despite temporal state

## Contracts To Preserve

- Queue timing is not subject identity by itself; Mind Graph stores the subject commitment.
- Temporal state can bias action-market candidates but cannot send directly.
- Explicit memory/history/factual/search/visual escalation still wins.
- Stage18 `micro_fast` routing remains governed only by existing lane rules.
- Owner shutdown, manual review, cooldown, and hard policy constraints remain final.
- Temporal records must stay compact, evidence-linked, and canonical-thread keyed.

## Done State

Stage20 is done when open loops and commitments survive restarts, interrupted lines can be recovered through ingress/action-market flow, due followups dedupe correctly, and acceptance plus replay/regression suites remain green.
