# Stage24 Scene-State Continuity Layer

## Goal

Stage24 turns Stage18 predictive continuity into a richer but still bounded per-thread `scene_state` layer.

The runtime should feel like it is living inside an unfolding interaction, not repeatedly reconstructing isolated turns from raw history.

## Boundary

- No second brain.
- No new unbounded always-on loop.
- No transport-side decision logic.
- No bypass of action-market-first deliberation.
- No regression of Stage17 fast-lane behavior for ordinary short turns.
- Explicit memory, history, factual, search, and visual turns still escalate before scene state can dominate.

## Data Contract

`scene_state` is persisted inside `active_thread_state` and exposed on every active-thread payload.

Minimum fields:

```json
{
  "shared_frame": "",
  "topic_stack": [],
  "salient_objects": [],
  "latent_questions": [],
  "predicted_branches": [],
  "relationship_trajectory": "",
  "response_sketch": "",
  "scene_confidence": 0.0,
  "freshness_at": ""
}
```

Boundaries:

- `topic_stack` <= 4
- `salient_objects` <= 4
- `latent_questions` <= 3
- `predicted_branches` <= 3
- compact summaries only, never raw-history dumps

Stage18 compatibility remains live:

- `active_thread_state.predictive_continuity` still exists
- `mind_packet.stage18` still exists
- Stage24 derives scene state from the same bounded active-thread state rather than replacing it with a planner

## Reducer Contract

Scene-state updates happen only through the existing active-thread reducer path:

1. inbound turn
2. inspect hydration
3. outbound reply or defer update

Default behavior is deterministic and bounded:

- dedupe and clip lists
- compact string summaries
- reuse the previous scene state on weak turns
- persist reducer metadata in `active_thread_state.metadata.stage24_scene`

Optional processor-backed scene compression is allowed only when:

- the turn is not on the ordinary short-turn hot path
- the turn is not an explicit memory/history/factual/search/visual escalation
- the turn is not attachment-heavy
- the reducer has enough semantic density to justify compression

If processor compression is unavailable or fails, Stage24 records `heuristic_fallback` and keeps deterministic heuristics.

## Prompt Contract

For ordinary `active-thread-fast` turns, prompt context order is now:

1. `continuity_summary`
2. `scene_state`
3. `scene_next`
4. `last_outbound_action`
5. `predictive_continuity`
6. optional one-line `last_exchange`

Verbatim history stays at `0-1` lines for ordinary short active-thread turns.

## Action-Market Contract

Stage24 adds a bounded advisory overlay after simulation and before policy sedimentation.

Each candidate can now expose:

- `scene_delta`
- `scene_rationale`

The overlay may:

- boost `reply_once` when a compact continuation is available
- boost `reply_multi` when real unfolding pressure is visible
- boost `defer_reply` when unresolved branches remain under low confidence
- penalize `silence` when continuity pressure is still active

The overlay must not:

- choose independently of the action market
- bypass explicit recall escalation
- bypass hard gates, send rules, or Stage22 canary controls

## Diagnostics

```bash
python -m holo_host show-scene-state --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-predicted-branches --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-scene-compression --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

Diagnostic payloads include:

- current `scene_state`
- compatibility `predictive_continuity`
- last reducer direction and time
- `compression_mode`
- `compression_reason`
- bounded truncation metadata
- source turn refs

## Acceptance

Stage24 is done when:

- `pytest -q` is green
- `accept-stage23` remains green
- `accept-stage24` is green
- scene state survives reload and restart
- ordinary short turns use scene state before verbatim history
- explicit memory queries still escalate
- Stage14, Stage17, and Stage22 regressions remain green

## Deferred Scope

Bounded subject programs are deferred beyond the live Stage24 scope.

Stage24 is a continuity-layer milestone, not a planner milestone.
