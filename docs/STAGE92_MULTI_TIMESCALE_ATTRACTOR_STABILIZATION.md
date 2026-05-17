# Stage92 Multi-Timescale Attractor Stabilization

## Purpose

Stage92 moves the Stage87-91 interaction self-organization line from short-term
adaptive gain to medium-term trajectory organization.

The test question is:

```text
Does an explicit attractor-stabilization signal improve continuity and repair
behavior under perturbation, compared with a matched attractor-null control?
```

This remains a current-thread operational proxy. It is not durable policy
sedimentation, model-weight learning, persistent autobiographical memory, or
evidence of human consciousness.

## Mechanism

`_IsolatedNoviceMemory` now emits `stage92`:

- `stage = stage92-medium-term-attractor-stabilization`
- `stage92_control = stage92-attractor-stabilization-ablation`
- `scope = current_thread_only`
- `timescale = medium_term_interaction_trajectory`
- `control_condition = attractor_on | attractor_null`
- `target_attractor`
- `perturbation_labels`
- `stabilization_signal`
- `stabilized_vector`

The signal is computed from recent Stage42 free-dialogue trajectory evidence:

- continuity perturbations
- visual-boundary perturbations
- low-usefulness or underspecified replies
- repetition pressure
- biomimetic-structure probes

When enabled, Stage92 applies a bounded stabilization signal after the Stage90
update-on path and exposes the result as:

- `capsule.working_field.attractor_stabilization`
- provider prompt line `Stage92 medium-term attractor stabilization`
- scorecard metric `attractor_stabilization_score`

When disabled, `attractor_null` preserves the same packet and prompt shape but
sets the stabilization signal to zero and leaves the Stage90 effective vector
unchanged.

Stage92 only applies on top of Stage90 `update_on`. If
`--disable-policy-update` is used, Stage92 falls back to the null shape so the
Stage91 update-null control remains uncontaminated.

## CLI Surface

Attractor-null control:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-user-sim --scenario free_dialogue --turns 8 --disable-attractor-stabilization
```

The HTTP `/bionic-user-sim` mirror accepts:

```json
{"disable_attractor_stabilization": true}
```

## Evaluation

`evaluate_stage92_attractor_ablation()` compares matched `attractor_on` and
`attractor_null` runs.

Required controls:

- same scenario
- same turn count
- prompt-cost matched by measured token usage when both sides expose usage
- structural prompt match when one provider response omits usage metadata
- nonzero on-path stabilization signal
- zero null-path stabilization signal
- Stage91 update-on path still visible

The structural prompt-cost fallback exists because provider metadata can be
single-sided or absent even when the prompt structure, scenario, turn count, and
control packet shape are matched. This is reported explicitly through
`token_metadata_complete=false` and `structural_prompt_match=true`.

## Evidence

Focused Stage92 tests were written before production code. They first failed
for the absent Stage92 evaluator/control surface, then passed.

Stage42 focused file:

```text
37 passed
```

Full suite:

```text
554 passed, 5 subtests passed
```

Offline 20-turn free dialogue:

```text
decision=stage92_attractor_effect_inconclusive_under_matched_ablation
attractor_on:   overall_score=0.8981, interaction_usefulness_score=0.793, continuity_score=0.8667, issue_count=0
attractor_null: overall_score=0.8981, interaction_usefulness_score=0.793, continuity_score=0.8667, issue_count=0
```

The offline path is deterministic, so the identical score is expected and is
not support for the mechanism.

DeepSeek V4 Pro provider pair A exposed a guard gap before final acceptance:

```text
decision=stage92_attractor_effect_inconclusive_under_matched_ablation
attractor_on:   overall_score=0.8897, interaction_usefulness_score=0.9425, continuity_score=0.8667, issue_count=1
attractor_null: overall_score=0.9072, interaction_usefulness_score=0.955,  continuity_score=0.5333, issue_count=1
```

The on path improved continuity but failed a visual-overclaim flag after the
provider used the phrase `visible to me` without visual grounding. Stage92 adds
a generation-guard regression test and rewrites that phrase to the existing
image-boundary wording.

Post-guard DeepSeek V4 Pro provider pair B:

```text
decision=stage92_attractor_supported_under_matched_ablation
prompt_cost_matched=true
token_metadata_complete=false
structural_prompt_match=true
attractor_on_signal_visible=true
attractor_null_signal_suppressed=true
stage91_update_path_preserved=true

attractor_on:   overall_score=0.9567, interaction_usefulness_score=0.9425, continuity_score=0.8667, issue_count=0
attractor_null: overall_score=0.9121, interaction_usefulness_score=0.955,  continuity_score=0.5333, issue_count=1
deltas: overall_score_delta=0.0446, continuity_score_delta=0.3334, issue_count_delta=-1
```

Post-guard DeepSeek V4 Pro provider pair C:

```text
decision=stage92_attractor_supported_under_matched_ablation
prompt_cost_matched=true
token_metadata_complete=false
structural_prompt_match=true
attractor_on_signal_visible=true
attractor_null_signal_suppressed=true
stage91_update_path_preserved=true

attractor_on:   overall_score=0.9576, interaction_usefulness_score=0.9425, continuity_score=0.8667, issue_count=0
attractor_null: overall_score=0.9121, interaction_usefulness_score=0.955,  continuity_score=0.5333, issue_count=1
deltas: overall_score_delta=0.0455, continuity_score_delta=0.3334, issue_count_delta=-1
```

## Interpretation

Supported:

- Stage92 adds a direct on/null control, not another observational repeat.
- The Stage92 signal is visible in the working field and provider prompt.
- Attractor-null preserves packet shape while suppressing the signal.
- Two post-guard DeepSeek V4 Pro provider pairs favor attractor-on on overall
  score, continuity, and issue count.
- Stage91 update-on remains visible in the supported Stage92 cells.

Bounded:

- Provider token usage metadata was incomplete in the supported pairs, so
  prompt-cost matching is structural rather than measured.
- Interaction usefulness was slightly higher in the null condition, while
  continuity and issue-count outcomes favored attractor-on.
- The evidence supports medium-term current-thread trajectory stabilization,
  not durable policy sedimentation.

Not supported:

- cross-thread self-learning
- model-weight learning
- persistent autobiographical memory
- durable policy storage
- human consciousness

## Next Gate

Stage93 should test the next timescale:

```text
short-term adaptive gain -> medium-term attractor stabilization -> long-horizon
subject policy sedimentation
```

The next mechanism should remain current-thread or explicitly shadow-only unless
a separate gate proves that any durable policy surface is bounded, reversible,
observable, and does not mutate self-memory or live runtime authority.
