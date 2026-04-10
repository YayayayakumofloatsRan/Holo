# Stage18 Engineering Handoff

## Target Change

Implement dual-speed subject continuity without adding a new loop:

- keep the Stage17 reflex lane for ordinary short WeChat turns
- add bounded predictive continuity inside active thread state
- let prediction bias, but never replace, action-market selection

## Files To Touch First

- `holo_host/mind_graph.py`
  - extend `active_thread_state` persistence and row decoding with `predictive_continuity`
  - update `update_active_thread_state()` to derive and expire predictions
- `holo_host/memory_bridge.py`
  - expose `mind_packet.stage18`
  - pass prediction into the existing packet/action-market path
  - keep explicit recall escalation higher priority than prediction
- `holo_host/processors.py`
  - render at most one predictive continuity line in fast prompts
  - keep `history_lines_in_prompt` semantics intact
- `holo_host/reply_api.py`
  - add `accept_stage18`
  - expose `/accept-stage18`
- `holo_host/cli.py`
  - add `accept-stage18`
- `holo_host/reply_service_parts/acceptance.py`
  - add the acceptance wrapper

## Tests To Add

- `tests/test_stage18_dual_speed_reflex.py`

Minimum cases:

- prediction is created after a bounded active thread update
- prediction has evidence refs, confidence, and expiry
- prediction is used as action-market bias on a same-thread follow-up
- selected action remains action-market-owned
- explicit memory query overrides prediction
- expired prediction is ignored
- canonical `wechat:<name>` identity is preserved
- Stage17 fast prompt history remains `0-1` lines

## Acceptance Command

```bash
python -m holo_host --config .holo_host.example.toml accept-stage18 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

Expected supporting checks:

```bash
pytest -q tests/test_stage18_dual_speed_reflex.py
pytest -q tests/test_stage17_realtime_runtime.py
python -m holo_host --config .holo_host.example.toml accept-stage17 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
pytest -q
```

## Contracts To Preserve

- Do not add a Stage18 daemon loop.
- Do not let prediction choose, send, or schedule.
- Do not add a transport-side branch for prediction.
- Do not bypass processor routing if a typed prediction task is later added.
- Do not expand fast prompts beyond one predictive line and one active-state history line.
- Do not treat low confidence or mere prediction mismatch as a deep recall reason.

## Implementation Notes

Use short TTLs for the first version. A stale prediction should fail closed and leave the turn to the normal Stage17/graph recall path.

Prediction evidence should reference local event ids, recent turn ids, or active-state metrics. Do not store raw long history windows in the prediction object.

The first implementation can use deterministic heuristics:

- unresolved reference implies `likely_recall_tier=recall`
- explicit pending line implies `likely_next_action_type=reply_once` or `continuity_defense`
- defer request implies `likely_next_action_type=defer_reply`
- high relationship tension lowers confidence and should not force a prediction

## Done State

Stage18 is done when Holo can carry a bounded next-turn expectation across the active thread path, use it as a visible action-market bias, and drop it safely when the real next turn does not match.
