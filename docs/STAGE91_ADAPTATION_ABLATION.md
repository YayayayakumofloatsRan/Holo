# Stage91 Adaptation Ablation

## Purpose

Stage91 makes the Stage90 self-organization claim falsifiable.

Stage90 showed that recent interaction failures can create a bounded
current-thread policy update. Stage91 asks the harder question:

```text
Does the update path matter when the prompt structure, scenario, and cost are
kept matched?
```

The control is `update_null`: Holo still emits the same `stage90` packet shape
and provider prompt line, but `update_delta` is forced to zero and the Stage89
effective vector remains the unmodified vector.

## Mechanism

`_IsolatedNoviceMemory` now accepts `enable_policy_update`.

When enabled:

- `control_condition = update_on`
- `update_enabled = true`
- `update_delta` is computed from recent score headroom and failure labels
- `updated_vector` is applied as Stage89 `effective_vector`

When disabled:

- `control_condition = update_null`
- `update_enabled = false`
- `update_delta` is all zeros
- `updated_vector` equals the Stage89 base vector
- `prompt_cost_matched_control = true`

The CLI exposes this as:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-user-sim --scenario free_dialogue --turns 8 --disable-policy-update
```

`evaluate_stage91_adaptation_ablation()` compares paired update-on and
update-null runs, checking same scenario, same turn count, matched token cost,
visible nonzero update in the update-on run, suppressed update in the null run,
and score/issue deltas.

## Biomimetic Interpretation

The bounded correspondence is test-time local adaptive gain:

```text
interaction outcome -> local error signal -> policy-gain update -> next reply
```

This remains a current-thread proxy. It is not durable autobiographical memory,
model-weight learning, or evidence of human consciousness.

The value for biomimetic research is narrower and stronger than Stage90:
Stage91 tests whether the adaptive-gain path is causally useful under a matched
null intervention.

## Evidence

Focused Stage91 tests were written first. They initially failed because
`evaluate_stage91_adaptation_ablation()` and the `update_null` path did not
exist. They now pass as part of the Stage42 suite:

```text
30 passed
```

Offline paired 20-turn free dialogue:

```text
decision=stage90_update_effect_inconclusive_under_matched_ablation
update_on:   overall_score=0.8981, interaction_usefulness_score=0.793, issue_count=0
update_null: overall_score=0.8981, interaction_usefulness_score=0.793, issue_count=0
```

The offline path is deterministic, so equal results are expected and should not
be used as evidence that the update improves interaction.

DeepSeek V4 Pro provider paired cell A:

```text
decision=stage90_update_supported_under_matched_ablation
same_scenario=true
same_turn_count=true
prompt_cost_matched=true
token_relative_delta=0.033
update_on_delta_visible=true
update_null_delta_suppressed=true

update_on:   overall_score=0.9525, interaction_usefulness_score=0.94, issue_count=0, total_tokens=5726
update_null: overall_score=0.9225, interaction_usefulness_score=0.9175, issue_count=2, total_tokens=5537
deltas: overall_score_delta=0.03, interaction_usefulness_score_delta=0.0225, issue_count_delta=-2
```

DeepSeek V4 Pro provider paired cell B:

```text
decision=stage90_update_supported_under_matched_ablation
same_scenario=true
same_turn_count=true
prompt_cost_matched=true
update_on_delta_visible=true
update_null_delta_suppressed=true

update_on:   overall_score=0.957, interaction_usefulness_score=0.94, issue_count=0
update_null: overall_score=0.9268, interaction_usefulness_score=0.9175, issue_count=2
deltas: overall_score_delta=0.0302, interaction_usefulness_score_delta=0.0225, issue_count_delta=-2
```

The null failures were not generic nonresponse failures. In the first provider
cell, the update-null run regressed into ungrounded image phrasing in later
resume and repair turns, including claims framed around an uploaded or attached
image even though the simulated turn had no visible image input. The update-on
run kept the image boundary grounded and avoided free-dialogue issues.

## Interpretation

Supported:

- update-null suppresses the Stage90 delta while preserving packet shape
- two independent real-provider matched cells favor update-on
- update-on improves overall and interaction-usefulness scores
- update-on removes the null-run issue count in both provider cells
- the improvement is concentrated in grounded interaction behavior, not a new
  memory write path

Bounded:

- offline deterministic output is inconclusive
- the second provider cell did not expose token usage metadata, so prompt-cost
  matching there is structural rather than measured
- `policy_update_delta_score` is a structural visibility score; it does not
  measure causal benefit by itself
- continuity alone is not the target metric, because the null run can maintain
  continuity while overclaiming visual context

Not supported:

- persistent self-learning
- model-weight learning
- durable policy sedimentation
- human consciousness
- solved long-horizon companionship

## Next Gate

The current self-organization line is now publishable as a bounded interaction
mechanism: a current-thread adaptive-gain loop with a matched null control and
two replicated provider cells.

The next research gate should move from single-agent local adaptation to
multi-timescale biomimetic organization:

```text
short-term adaptive gain -> medium-term attractor stabilization -> long-horizon
subject policy sedimentation
```

That next step must still keep biological and consciousness language bounded to
operational proxies unless new falsification controls justify stronger claims.
