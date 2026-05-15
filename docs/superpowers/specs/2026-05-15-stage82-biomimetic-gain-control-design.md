# Stage82 Biomimetic Gain Control Design

## Goal

Complete the remaining Stage78 direct falsification control by testing
neuromodulatory adaptive gain over existing Stage59/60-gated real-provider
trace artifacts without spending provider tokens or widening runtime authority.

## Context

Stage79 executed GNW ignition-null control, Stage80 executed hippocampal/CLS
marker removal, and Stage81 executed predictive-processing neutral salience.
The only remaining direct-control row is neuromodulatory gain-clamp or
salience-matched random-gain. Stage82 uses gain clamp first because it is a
direct first-principles test of the mapped variables: dopamine,
norepinephrine, acetylcholine, and serotonin are the adaptive-gain surface in
the Stage70 observatory.

## Design

Stage82 adds `holo_host/biomimetic_gain_control.py` and CLI command
`evaluate-biomimetic-gain-control`. The evaluator consumes Stage78 theory JSON,
Stage81 precision-control JSON, and one or more real-provider trace JSON files.

For each trace, the evaluator builds two paired conditions:

- baseline observed trace
- neuromodulatory gain clamp where dopamine, norepinephrine, acetylcholine,
  and serotonin are all set to neutral `0.5`

The clamp preserves salience, consolidation priority, replay phase, recall
budget, prompt-cost proxy, and boundary state. This isolates whether the
neuromodulator-coupling proxy is sensitive to adaptive gain while checking that
the replay/correction chain remains above threshold.

## Acceptance

- Stage81 precision-control precondition must be supported.
- All supplied traces must be real-provider Stage59/60-gated traces.
- Neuromodulator-coupling proxy must drop in all supplied cells.
- Correction survival must remain above threshold after the clamp.
- Prompt-cost, reactivation-phase, and boundary deltas must remain zero.
- Output must include HTML, JSON, and PNG artifacts.
- Evidence language must stay bounded and must not claim subjective
  consciousness or biological neuromodulation.

## Boundary

Stage82 is read-only over existing evidence. It does not call providers, start
WeChat, mutate runtime state, write self-memory, write policy, add watcher
authority, add runtime decision authority, or run an unbounded loop.
