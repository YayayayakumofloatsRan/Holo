# Engineering Handoff Stage 13

## What Changed
- Stage13 adds persistent empirical action-calibration rows to `mind_graph`.
- Stage13 preserves recent outcome/prediction history inside world state instead of only the last calibration event.
- Stage13 feeds calibration back into action simulation as an inspectable overlay rather than an opaque replacement score.
- Stage13 adds `show-action-calibration`, `trace-outcome-history`, `trace-action-prediction-error`, and `accept-stage13`.

## What To Verify
- Calibration stats survive restart and keep canonical `wechat:<name>` buckets for ordinary direct messages.
- Confidence can go down after degraded or inconsistent evidence.
- Negative realized deltas remain visible in history and traces.
- Empirical overlay can change candidate ranking in a controlled fixture.
- Action-market-first flow is still intact.

## What Not To Change
- Do not add a second decision layer.
- Do not add a new daemon loop just to maintain calibration.
- Do not replace heuristics with an opaque learned score.
- Do not weaken runtime/operator safety boundaries.

## Recommended Follow-Up
- Tighten scenario bucket definitions only if replay evidence shows obvious over-bucketing.
- Continue moving state updates toward reducer-style evidence summaries instead of direct heuristic mutation.
