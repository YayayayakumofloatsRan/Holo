# Stage 12 Outcome Closure And Canonical Identity

## Goal
Seal Stage11 by making ordinary reply-path actions produce evidence-backed outcome appraisal records and by keeping reply-path identity canonical and stable.

## Boundary
- No second brain layer.
- No new always-on loop.
- No weakening of operator safety boundaries.
- Keep action-market-first deliberation.
- Keep memory as self, processor as replaceable compute, and transport as eyes and hands.

## Expected Data Contract
- Reply-path actions should carry provenance for:
  - `event_row_id`
  - `message_id`
  - `thread_key`
  - `selected_action`
  - `selected_prediction`
  - `usage_evidence_refs`
  - `source`
- Outcome appraisal should prefer action-local usage evidence over a global recent-usage sum.
- Acceptance surfaces should stay machine-readable.

## Acceptance Checklist
- Ordinary `reply_once`, `reply_multi`, `defer_reply`, `push_back`, `counter_offer`, `continuity_defense`, and `silence` paths can surface outcome appraisal metadata.
- Action appraisal rows stay tied to their own `action_ref`.
- Clean reload preserves the latest calibration state.
- `accept-stage12` returns a structured pass/fail report.

## Rollback Notes
- If appraisal provenance regresses, keep the previous reply behavior and restore the action-local evidence handoff first.
- If identity handling regresses, stop at the reply-path boundary before widening the memory contract.
