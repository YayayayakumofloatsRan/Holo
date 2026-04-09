# Engineering Handoff Stage 12

## What Changed
- Stage12 closes the reply-path outcome loop by attaching appraisal to ordinary actions.
- Stage12 keeps outcome evidence local to the action when local usage rows are available.
- Stage12 adds `accept-stage12` as the acceptance gate for the new closure surface.

## What To Verify
- Ordinary reply-path actions produce appraisal rows with provenance.
- `usage_evidence_refs` are present and machine-readable.
- Reply-path action refs stay local to the action.
- Clean reload preserves the last calibration state.
- Helper contracts continue to pass.

## What Not To Change
- Do not add a second brain layer.
- Do not relax transport safety.
- Do not bypass the action market.
- Do not add a new always-on repair loop.

## Recommended Follow-Up
- Keep tightening reducer-style state updates.
- Keep improving evidence locality before expanding any higher-level reasoning surface.
