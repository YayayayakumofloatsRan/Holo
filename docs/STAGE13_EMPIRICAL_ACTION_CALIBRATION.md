# Stage 13 Empirical Action Calibration

## Goal
Turn outcome calibration from a last-turn error record into a persistent empirical overlay that can influence action selection while keeping heuristics as visible priors.

## Boundary
- No second brain layer.
- No black-box ML training.
- No new always-on loop.
- No weakening of operator safety boundaries.
- Keep action-market-first deliberation.

## Expected Data Contract
- Persistent action-calibration rows are keyed by:
  - `action_type`
  - `channel`
  - `thread_key_bucket`
  - `scenario_bucket`
- Minimum persistent fields:
  - `support_count`
  - `recent_support_count`
  - `avg_reply_latency`
  - `ignored_rate`
  - `correction_rate`
  - `response_quality_mae`
  - `relational_delta_mae`
  - `risk_mae`
  - `confidence`
  - `last_updated_at`
- `metadata_json` should remain inspectable and carry recent errors/outcomes, evidence refs, and last prediction/realized payloads.
- Candidate simulation should expose:
  - `empirical_calibration`
  - `empirical_overlay_delta`
  - `calibration_bucket`
  - `calibration_confidence`

## Acceptance Checklist
- Calibration rows persist across reload.
- Support counts increase after replay/appraisal.
- Confidence can decrease when evidence quality worsens.
- Negative relational or identity deltas remain representable.
- At least one controlled fixture shows the empirical overlay changing action ranking.
- `show-action-calibration`, `trace-outcome-history`, `trace-action-prediction-error`, and `accept-stage13` return machine-readable payloads.

## Rollback Notes
- If ranking behavior regresses, keep the persistent calibration rows and disable only the overlay contribution inside action simulation.
- If confidence becomes unstable, revert the confidence reducer before removing the trace surfaces.
