# Stage18 Dual-Speed Reflex And Predictive Continuity

## Goal

Stage18 extends Stage17 from thread-resident short-turn state into dual-speed subject continuity:

- a reflex lane for ordinary short WeChat turns that still uses `ActiveThreadState`
- a predictive continuity lane that records what the current turn makes likely on the next turn

The result should feel less like Holo is only reacting to the current message and more like Holo is carrying a near-future thread shape forward.

## Boundary

- No second brain layer.
- No new unbounded always-on loop.
- No transport-side decision logic.
- No new direct processor path outside the processor fabric.
- No live repo hot edits.
- Prediction is advisory only. It may bias the action market, but it must not select or execute an action by itself.
- Preserve memory-is-self, processor-replaceable, transport-eyes-hands, canonical WeChat identity, and action-market-first deliberation.

## Runtime Shape

Stage18 has two internal speeds.

The reflex speed is the existing Stage17 `active-thread-fast` route. It should keep ordinary short turns on a warm active state path, keep prompt history at `0-1` lines, and keep recall escalation tied to concrete reasons.

The predictive speed is a bounded state reducer that runs as part of the normal ingress/outbound update path. It records a likely next need for the same canonical thread. It is not a daemon loop and it is not a scheduler.

The first implementation should prefer deterministic reducers over new model calls. If a future patch needs processor help, it must use a typed processor task through the existing processor fabric and must record usage in the processor ledger.

## Data Contract

`mind_graph.active_thread_state` should expose a nested `predictive_continuity` object through `MemoryBridge.active_thread_state()` and `mind_packet.active_thread_state`.

Minimum fields:

```json
{
  "expected_next_need": "",
  "likely_next_action_type": "",
  "likely_recall_tier": "fast",
  "recall_preheat_keys": [],
  "unresolved_next_refs": [],
  "prediction_confidence": 0.0,
  "expires_at": "",
  "evidence_refs": [],
  "source": "stage18_reducer",
  "updated_at": ""
}
```

`mind_packet.stage18` should include:

```json
{
  "prediction_available": false,
  "prediction_used_as_bias": false,
  "prediction_confidence": 0.0,
  "prediction_reason": "",
  "prediction_expired": false,
  "action_market_bias_applied": false,
  "max_predictive_prompt_lines": 1
}
```

`active_thread_state.metrics` should add bounded counters:

- `prediction_created`
- `prediction_used`
- `prediction_expired`
- `prediction_missed`
- `prediction_recall_escalation_overrode`

## Action Market Contract

Predictive continuity can bias candidate scores only after candidates are already built by the subject runtime.

Allowed bias targets:

- `reply_once`
- `reply_multi`
- `defer_reply`
- `history_refresh`
- `external_lookup`
- `push_back`
- `counter_offer`
- `continuity_defense`

Forbidden behavior:

- selecting an action directly from `predictive_continuity`
- sending from the prediction reducer
- suppressing explicit recall escalation because a prediction exists
- injecting more than one predictive line into fast-lane prompts

## Acceptance Checklist

Closure command:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage18 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The acceptance gate should verify:

- `accept-stage17` remains green.
- Ordinary short turns still use `active_thread` memory route.
- Fast-lane prompt history remains `0-1` lines.
- A normal inbound/outbound pair creates `predictive_continuity` with evidence refs and an expiry.
- A follow-up synthetic turn can use the prediction as action-market bias.
- The selected action still comes from the action market.
- Explicit memory/history/factual recall requests override the prediction.
- Expired predictions are ignored and counted as expired.
- No new daemon loop is required for Stage18.

Recommended regression commands:

```bash
pytest -q tests/test_stage18_dual_speed_reflex.py
pytest -q tests/test_stage17_realtime_runtime.py
python -m holo_host --config .holo_host.example.toml accept-stage17 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage18 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
pytest -q
```

## Regression Risks

- Prediction becomes a hidden action selector instead of an action-market bias.
- Stale predictions cause Holo to answer the expected next turn rather than the real current turn.
- Prediction state leaks across canonical thread keys.
- Fast prompts grow back into multi-line recent-history prompts.
- Low-confidence prediction suppresses recall that should escalate.
- A model-specific prediction task sneaks around the processor fabric.

## Rollback

Stage18 should be rollback-safe by ignoring `predictive_continuity` and falling back to Stage17 active-thread behavior. The data should be additive and optional; missing Stage18 fields must not break `active-thread-fast`, graph recall, or replay.
