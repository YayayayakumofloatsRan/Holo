# Stage20 Engineering Handoff

## Target Change

Persist temporal commitments and route due recovery through the action market.

## Files To Touch First

- `holo_host/store.py`
  - keep queue timing authoritative
  - expose enough job state for commitment linking
- `holo_host/mind_graph.py`
  - persist temporal commitment meaning and state transitions
  - provide query helpers for due/open commitments
- `holo_host/memory_bridge.py`
  - expose `mind_packet.stage20`
  - add due commitments to packet/action-market context
- `holo_host/reply_api.py`
  - create commitments for `defer_reply` and interrupted selected actions
  - mark commitments fulfilled/superseded/canceled from outcomes
  - add `accept_stage20`
- `holo_host/cli.py`
  - add `accept-stage20`
- `holo_host/reply_service_parts/acceptance.py`
  - add acceptance wrapper

## Tests To Add

- `tests/test_stage20_temporal_commitments.py`

Minimum cases:

- `defer_reply` creates a commitment and queue job
- due commitment is visible in `mind_packet.stage20`
- action market owns recovery selection
- duplicate due job does not duplicate recovery
- fulfilled commitment does not reappear
- expired commitment is ignored
- restart simulation recovers an interrupted event once
- policy/manual-review blockers still win

## Acceptance Command

```bash
python -m holo_host --config .holo_host.example.toml accept-stage20 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

Expected supporting checks:

```bash
pytest -q tests/test_stage20_temporal_commitments.py
pytest -q tests/test_stage19_attention_frontier.py tests/test_stage18_dual_speed_reflex.py
python -m holo_host --config .holo_host.example.toml accept-stage20 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
pytest -q
```

## Contracts To Preserve

- Queue timing is not subject identity by itself; Mind Graph stores the subject commitment.
- Commitment recovery cannot send directly.
- Owner shutdown, manual review, and hard policy constraints remain final.
- Code/operator paths remain shadow-write only.
- Commitment records must carry evidence refs and canonical thread keys.

## Implementation Notes

Treat commitment creation as part of action/outcome bookkeeping, not as a free-floating planner.

Commitment state should be compact and inspectable. Store summaries and refs, not raw transcript windows.

Restart recovery should look for incomplete event/action records and create at most one recovery commitment per source event.

## Done State

Stage20 is done when Holo can remember a bounded temporal obligation, survive interruption/restart, and recover through normal action-market deliberation.
