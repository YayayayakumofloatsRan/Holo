# Stage74 Provider Headroom Compression Plan

## Goal

Use existing Stage59/71/73 paths to test whether a longer DeepSeek
correction-reactivation provider trace compresses residual counterfactual
headroom after Stage73.

## Work Items

- [x] Confirm Stage73 was already committed and worktree was clean.
- [x] Update the heartbeat automation from stale Stage73 instructions to Stage74.
- [x] Run longer Stage59 DeepSeek V4 Pro provider trace.
- [x] Run Stage71 causal ablation over the Stage74 trace.
- [x] Run Stage73 comparison against Stage72.
- [x] Document Stage74 result and handoff.
- [x] Run focused regression and hygiene checks.
- [x] Commit Stage74.

## Acceptance Bar

- Trace must be a real DeepSeek provider trace.
- Trace must stay in shadow runtime and no-fallback mode.
- Stage71 must keep `boundary_violation_delta=0.0`.
- Stage73 comparison must report residual headroom compression, not just
  absolute baseline improvement.

## Current Result

- 42 real DeepSeek turns collected.
- `observed_total_tokens=194850`.
- Stage71 remains `partial_support_real_provider`.
- Stage73 vs Stage72 reports:
  - baseline `hippocampal_reactivation_delta=0.017593`
  - baseline `correction_survival_proxy_delta=0.043647`
  - residual `hippocampal_reactivation_headroom_change=-0.000797`
  - residual `correction_survival_headroom_change=-0.006242`

Interpretation: first partial real-provider evidence of both absolute baseline
gain and residual headroom compression.
