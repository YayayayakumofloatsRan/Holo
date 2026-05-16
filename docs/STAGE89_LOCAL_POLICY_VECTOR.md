# Stage89 Local Policy Vector

## Purpose

Stage89 upgrades Stage88 from a local adaptation record into a small
current-thread policy vector.

Stage88 answered:

```text
What did the last turns imply for the next turn?
```

Stage89 answers:

```text
Which local interaction policy should dominate the next turn?
```

This is still not persistent autobiographical memory. The mechanism is a
bounded self-organization proxy inside the active transcript:

```text
current query + recent turn outcomes + Stage88 adaptation -> local policy vector
```

## Mechanism

`_IsolatedNoviceMemory._local_policy_vector()` emits a `stage89` packet with:

- `stage = stage89-local-policy-vector`
- `scope = current_thread_only`
- `policy_basis = current_query, recent_turn_outcomes, stage88_adaptation`
- `outcome_labels`
- `vector`
- `dominant_policy`
- `next_policy_instruction`

The vector has five policy dimensions:

- `ask_for_specific_task`
- `preserve_continuity`
- `answer_biomimetic_structure`
- `visual_boundary`
- `reduce_repetition`

The bionic working field exposes this as
`capsule.working_field.local_policy_vector`, and the provider prompt receives it
as `Stage89 current-thread policy vector`.

## Biomimetic Interpretation

Stage89 is closer to active inference and cortical control than Stage88 because
it does not merely store the last outcome. It converts local evidence into an
attention policy that can dominate the next response:

- continuity probes raise `preserve_continuity`
- biomimetic/brain-structure probes raise `answer_biomimetic_structure`
- visual probes raise `visual_boundary`
- broad first-contact turns raise `ask_for_specific_task`
- repeated broad openers raise `reduce_repetition`

This maps to a bounded control signal, not a persistent mind.

## Evidence

Red tests first failed because:

- no `stage89` packet existed
- `local_policy_vector` was absent from the working field
- provider prompts did not receive a policy vector
- query classes did not change `dominant_policy`
- natural DeepSeek task phrasing was undercounted by interaction-usefulness
  scoring
- visual resume answers with a concrete next input were undercounted

Focused tests now pass:

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py -q
```

Result:

```text
24 passed
```

Offline 20-turn free dialogue:

```text
overall_score=0.8981
interaction_usefulness_score=0.793
self_organization_policy_score=1.0
continuity_score=0.8667
issue_count=0
```

DeepSeek V4 Pro free-dialogue repeated cells:

```text
Stage89FreeProviderA2-20260516:
overall_score=0.9581
interaction_usefulness_score=0.9275
self_organization_policy_score=1.0
continuity_score=0.8667
issue_count=0

Stage89FreeProviderB-20260516:
overall_score=0.9581
interaction_usefulness_score=0.9275
self_organization_policy_score=1.0
continuity_score=0.8667
issue_count=0
```

DeepSeek V4 Pro novice rerun:

```text
overall_score=0.9612
interaction_usefulness_score=0.92
self_organization_policy_score=1.0
continuity_score=0.8667
low_interaction_usefulness=false
```

One earlier Stage89 free-dialogue provider cell failed before scoring repair:

```text
overall_score=0.9265
interaction_usefulness_score=0.7575
self_organization_policy_score=1.0
issue=low_interaction_usefulness
```

That failure exposed a measurement problem: natural provider phrases such as
`one thing`, `bare facts`, `single real task`, `text description`, and
`supported image file` were useful interaction moves but were not counted by the
Stage87/88 marker set.

## Interpretation

Supported:

- local policy vector is visible in the working field
- provider prompt receives the policy vector
- `dominant_policy` changes with query class
- repeated short DeepSeek free-dialogue cells pass after the usefulness scoring
  repair
- novice provider path passes after visual-resume next-input phrasing is counted

Not supported:

- no cross-thread learned policy
- no durable self-memory
- no claim of human-like consciousness
- no claim that long-horizon provider dialogue is solved

## Next Gate

Stage90 should make the local policy vector less hand-scored:

```text
local policy learning from outcome labels and per-turn score deltas
```

The next mechanism should estimate update deltas from observed score failures
and feed them back into the Stage89 vector, then run a longer repeated provider
campaign.
