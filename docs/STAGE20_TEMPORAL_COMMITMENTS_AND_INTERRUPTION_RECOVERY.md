# Stage20 Temporal Commitments And Interruption Recovery

## Goal

Stage20 makes Holo's near-future obligations durable:

- deferred replies
- explicit promises to come back to a point
- interrupted actions
- pending recovery after a runtime restart

The goal is not more autonomy. The goal is that Holo does not lose a live commitment just because the current processor turn, daemon cycle, or transport session ended.

## Boundary

- No scheduler-brain.
- No new unbounded loop.
- No new proactive send rights.
- No commitment without evidence.
- No commitment may override owner shutdown, policy, cooldown, or manual review mode.
- No transport-side decision logic.
- Preserve action-market-first deliberation.

## Runtime Shape

Stage20 should separate timing from meaning:

- `QueueStore` remains the timing and job surface.
- Mind Graph stores the subject commitment and recovery meaning.
- Action market decides whether a due commitment becomes `reply_once`, `defer_reply`, `history_refresh`, `operator`, or `silence`.

Commitments can be created from:

- selected `defer_reply`
- explicit user request to revisit something
- interrupted `external_lookup`, `history_refresh`, `visual_recall`, or operator-shadow action
- restart recovery when an event was ingested but no final action was written

## Data Contract

Minimum `temporal_commitment` fields:

```json
{
  "commitment_id": "",
  "channel": "wechat",
  "thread_key": "wechat:Nemoqi",
  "chat_name": "Nemoqi",
  "source_event_id": "",
  "source_action_type": "",
  "summary": "",
  "state": "open",
  "due_at": "",
  "recovery_action": "",
  "queue_job_id": "",
  "interruption_reason": "",
  "evidence_refs": [],
  "created_at": "",
  "updated_at": ""
}
```

Allowed states:

- `open`
- `scheduled`
- `due`
- `fulfilled`
- `superseded`
- `canceled`
- `expired`

`mind_packet.stage20` should include:

```json
{
  "commitment_visible": false,
  "commitment_due": false,
  "commitment_id": "",
  "recovery_action": "",
  "interruption_recovered": false,
  "duplicate_recovery_blocked": false
}
```

## Action Market Contract

Due commitments must enter the action market as candidates or candidate modifiers. They must not execute directly.

Examples:

- due deferred reply -> candidate `reply_once` or `defer_reply`
- interrupted history refresh -> candidate `history_refresh`
- explicit revisit request -> candidate `reply_once` with continuity context
- unsafe or stale commitment -> candidate `silence` or `defer_reply` with reason

## Acceptance Checklist

Closure command:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage20 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The acceptance gate should verify:

- Stage19 remains green.
- A selected `defer_reply` creates one commitment and one queue job.
- A due commitment re-enters the action market rather than sending directly.
- A fulfilled commitment is marked fulfilled and not retried.
- Duplicate recovery is blocked after restart simulation.
- Expired or canceled commitments do not affect packets.
- Explicit owner/policy/manual-review blockers still win.
- Commitment state uses canonical `wechat:<name>` thread identity.

Recommended regression commands:

```bash
pytest -q tests/test_stage20_temporal_commitments.py
pytest -q tests/test_stage19_attention_frontier.py tests/test_stage18_dual_speed_reflex.py
python -m holo_host --config .holo_host.example.toml accept-stage20 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
pytest -q
```

## Regression Risks

- Commitment jobs send without action-market selection.
- Deferred replies duplicate after restart.
- Commitments persist forever and create stale pressure.
- Commitment recovery ignores manual review or owner shutdown.
- Interrupted operator/code paths hot-edit the live repo.
- Thread identity splits between `wechat:<name>` and bare aliases.

## Rollback

Stage20 should degrade by ignoring commitment state and leaving existing queue behavior intact. Existing deferred reply jobs should remain readable by `QueueStore`.
