# Stage43: Motivational Dynamics Field

## Goal
Stage43 turns the Stage42 observational `bionic_state` into a bounded internal dynamics surface. The goal is not to add a new personality layer or a second brain; it is to expose replay-stable pressure, affect, unfinished-loop tension, diffuse attention, attention center, and bounded stochasticity before action selection.

## Theory Contract
The working hypothesis is that bionic behavior should emerge from continuous control pressure rather than fixed reply rules. Stage43 models emotion and motivation as bounded control variables that modulate attention and action-market scores:
- `arousal`
- `valence`
- `uncertainty`
- `curiosity`
- `attachment_pressure`
- `fatigue`
- `identity_coherence`
- `unfinished_loop_pressure`

These values are not user-facing feelings and are not claims of consciousness. They are inspectable control-state variables that make the bionic loop easier to debug.

## Runtime Contract
`motivational_field` is computed after perception and working-field assembly, before action selection. It can only add bounded score deltas to existing action-market candidates.

Hard constraints:
- No second brain.
- No self-memory write.
- No new unbounded loop.
- No transport decision authority.
- No direct model/tool execution.
- No action outside action-market selection.
- Bounded stochasticity must be deterministic from stable input hashes.

## Capsule Surface
Every bionic capsule now includes top-level `motivational_field`:
- `stage`: `stage43-motivational-dynamics-field`
- `field_model`: `motivational_dynamics_v1`
- `decision_authority`: `action_market_bias_only`
- `dynamics_state`: bounded continuous control variables
- `attention`: `attention_center` plus `diffuse_attention`
- `stochasticity`: stable seed and bounded noise
- `candidate_biases`: per-action bias deltas
- `contracts`: replay-stable and safety invariants

`bionic_state` also carries a compact projection of this field so operator review can see how the visible subject state relates to motivation.

## Action-Market Integration
Stage43 applies a small `motivation_delta` to action candidates and preserves:
- `score_before_motivation`
- `motivation_delta`
- `motivation_attention_center`
- `motivation_rationale`

The maximum absolute delta is `0.08`. The overlay can nudge candidate order but cannot bypass the action market or execute any side effect.

## Acceptance
`accept-stage43` composes `accept-stage42`, then verifies:
- `motivational_field` is visible.
- Repeated same-input probes produce the same field.
- Bounded stochasticity remains within `+/-0.03`.
- Action-market deltas remain within `+/-0.08`.
- Stage29/30 phase order is unchanged.
- WeChat transport remains off.
- Self-memory remains unwritten.

Required validation:
- `pytest -q tests/test_stage43_motivational_dynamics.py`
- `pytest -q tests/test_stage29_bionic_cli_agent.py tests/test_stage39_bionic_turing_benchmark.py tests/test_stage42_bionic_user_sim.py tests/test_stage43_motivational_dynamics.py`
- `python -m holo_host --config .holo_host.toml accept-stage43 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
- `git diff --check`
