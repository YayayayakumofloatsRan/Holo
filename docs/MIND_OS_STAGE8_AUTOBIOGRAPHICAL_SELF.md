# Holo MindOS Stage-8

## Theme
- Autobiographical continuity
- Long-horizon goals
- Identity/goal-led deliberation

## What Changed
- `autobiographical_state` is now a first-class subject state instead of a prompt-side summary.
- `goal_state` now persists cross-turn commitments, progress, conflicts, and next windows.
- Stage-8 daemon loops (`autobiographical_consolidation`, `goal_arbitration`, `continuity_audit`) write back into the same subject core used by reply, initiative, resistance, lookup, and operator paths.
- Deliberation now evaluates not only world-state and counterfactual outcome, but also whether an action fits the current chapter of self and the active long-horizon goals.

## Visibility Rules
- Ordinary chat stays implicit by default.
- Autobiographical explanation only surfaces when continuity, self-explanation, commitments, or explicit change questions make it relevant.
- Expression budget remains constrained; Stage-8 must not regress into long autobiographical monologues.

## Acceptance
- `accept-stage8` must pass before returning online.
- The stage is only complete when Holo can explain why she changed, keep cross-day goals alive, remain concise in low-pressure chat, and expose a traceable autobiographical/goal causality chain.
