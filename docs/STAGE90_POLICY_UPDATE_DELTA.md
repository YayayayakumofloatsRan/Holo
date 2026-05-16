# Stage90 Policy Update Delta

## Purpose

Stage90 makes the Stage89 local policy vector less hand-scored by adding a
current-thread update delta from observed score failures.

Stage89 answered:

```text
Which local policy should dominate the next turn?
```

Stage90 answers:

```text
How should the local policy change after the last turn failed or left headroom?
```

The mechanism stays inside the active transcript. It does not write durable
self-memory, mutate policy storage, or claim a persistent self.

## Literature Anchor

The design is aligned with three bounded ideas from current AI and
neuroscience-adjacent literature:

- Active inference treats policy selection as inference under expected free
  energy and can express information-seeking behavior from uncertainty and
  preference terms: [Sajid et al., 2021](https://arxiv.org/abs/2110.04074).
- Recent active-inference LLM work proposes a cognitive layer that adjusts
  prompts and search strategies above an LLM rather than changing model
  weights: [Active Inference for Self-Organizing Multi-LLM Systems, 2024](https://arxiv.org/abs/2412.10425).
- LLM agent self-improvement work uses feedback from prior outcomes to improve
  later behavior without immediate model fine-tuning: [Reflexion, 2023](https://arxiv.org/abs/2303.11366)
  and [Self-Refine, 2023](https://arxiv.org/abs/2303.17651).

Stage90 uses these as engineering analogies only. It is not a biological brain
model and not proof of consciousness.

## Mechanism

`_IsolatedNoviceMemory.observe_turn()` now stores a compact outcome record for
each observed turn:

- `interaction_usefulness_score`
- `score_delta = max(0, 0.9 - interaction_usefulness_score)`
- `failure_labels`

`_IsolatedNoviceMemory._local_policy_update()` consumes the recent outcome
records and emits `stage90`:

- `stage = stage90-outcome-score-delta-update`
- `scope = current_thread_only`
- `update_basis = recent_turn_score_delta, failure_labels, stage89_vector`
- `source_outcome_count`
- `largest_score_delta`
- `failure_labels`
- `update_delta`
- `updated_vector`
- `dominant_policy_after_update`

The update is bounded and small. It can raise the five Stage89 policy
dimensions, but it cannot add a new action type or bypass the existing
action-market authority.

## Biomimetic Interpretation

The biomimetic correspondence is a local prediction-error and gain-adjustment
proxy:

```text
interaction failure -> score delta -> policy gain update -> next attention target
```

This is closer to adaptive behavior than Stage89 because the policy vector now
responds to measured outcome headroom instead of only current query class.

Examples:

- weak answer to a screenshot query raises `visual_boundary`
- weak answer to a continuity probe raises `preserve_continuity`
- weak first-contact answer raises `ask_for_specific_task`
- repeated broad openers raise `reduce_repetition`

## Evidence

Red tests first failed because:

- no `stage90` packet existed
- `local_policy_update` was absent from the working field
- provider prompts did not include outcome-score update evidence

Focused tests now pass:

```powershell
python -m pytest tests\test_stage42_bionic_user_sim.py -q
```

Result:

```text
27 passed
```

Offline 20-turn free dialogue:

```text
overall_score=0.8981
interaction_usefulness_score=0.793
self_organization_policy_score=1.0
policy_update_delta_score=1.0
continuity_score=0.8667
issue_count=0
```

DeepSeek V4 Pro repeated free-dialogue cells:

```text
Stage90FreeProviderA-20260516:
overall_score=0.9525
interaction_usefulness_score=0.96
self_organization_policy_score=1.0
policy_update_delta_score=1.0
continuity_score=0.8667
issue_count=0

Stage90FreeProviderB-20260516:
overall_score=0.9572
interaction_usefulness_score=0.96
self_organization_policy_score=1.0
policy_update_delta_score=1.0
continuity_score=0.8667
issue_count=0
```

DeepSeek V4 Pro longer free-dialogue cell:

```text
Stage90FreeProvider12-20260516:
overall_score=0.9569
interaction_usefulness_score=0.9467
self_organization_policy_score=1.0
policy_update_delta_score=1.0
continuity_score=0.8667
issue_count=0
```

DeepSeek V4 Pro novice cell:

```text
Stage90NoviceProvider-20260516:
overall_score=0.9645
interaction_usefulness_score=0.936
self_organization_policy_score=1.0
policy_update_delta_score=1.0
continuity_score=0.8667
low_interaction_usefulness=false
```

## Interpretation

Supported:

- score failures create bounded policy deltas
- the working field exposes `local_policy_update`
- provider prompts receive `Stage90 outcome-score update`
- repeated short DeepSeek cells remain stable
- one longer 12-turn DeepSeek cell passes with no free-dialogue issues

Not supported:

- no durable policy sedimentation
- no cross-thread self-learning
- no model-weight learning
- no claim of human consciousness
- no claim that long-horizon free dialogue is solved

## Next Gate

Stage91 should move from heuristic score deltas to a small publication-grade
experiment:

```text
paired adaptation ablation over provider cells
```

Acceptance should compare Stage90 update-on versus update-null cells under the
same prompt cost and scenario mix, then report whether interaction usefulness
and repetition/continuity errors improve beyond provider-cell noise.
