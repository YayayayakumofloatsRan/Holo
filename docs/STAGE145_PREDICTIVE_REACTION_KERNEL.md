# Stage145 Predictive Outcome And Reaction Kernel Shadow

Date: 2026-05-24

## Purpose

Stage145 adds a deterministic prediction-error loop and a shadow reaction-kernel parameter layer over the Stage139-144 trust and packet surfaces.

The goal is to make Holo report:

```text
what it expected the turn needed
what outcome would have been best
what actually happened
how large the prediction error was
which local reaction tendency would change
```

Stage145 is shadow-only. It does not apply parameter deltas, mutate durable policy, learn model weights, write self-memory, call a provider, execute tools, change transport behavior, or start WeChat.

## Schemas

```text
holo.stage145.outcome_appraisal.v1
holo.stage145.reaction_kernel_shadow.v1
```

## Reaction Kernel Parameters

Stage145 represents local reaction tendency as bounded floats in `[0, 1]`:

- `directness`
- `caution`
- `memory_trust`
- `tool_preference`
- `clarification_threshold`
- `continuation_threshold`
- `novelty_threshold`
- `verbosity_bias`
- `correction_sensitivity`
- `risk_aversion`
- `initiative_bias`
- `affective_warmth`

The current implementation uses deterministic defaults and produces proposed deltas only. No proposed value is applied to runtime policy.

## Inputs

`holo_host/stage145_reaction_kernel.py` consumes existing evidence only:

- Stage139 tool grounding
- Stage140 memory grounding
- Stage141 memory alignment
- Stage142 semantic novelty
- Stage143 packet budget
- Stage144 context economy
- selected action and reply metadata when present

It does not read private memory files directly.

## Outcome Appraisal

The outcome appraisal report contains:

- `predicted_user_need`
- `predicted_best_outcome`
- `predicted_risk`
- `predicted_uncertainty_reduction`
- `observed_grounding_status`
- `observed_memory_grounding_status`
- `observed_memory_alignment_status`
- `observed_stage142_status`
- `observed_packet_waste`
- `observed_context_sufficiency`
- `stage143_stop_reason`
- `stage144_recommended_deep_policy`
- `prediction_error`
- `kernel_delta_candidates`
- `shadow_only=true`

Prediction error is a bounded deterministic score. It rises when grounding fails, memory details are unsupported or contradicted, Stage142 suppresses a duplicate continuation, packet waste is high, or context sufficiency is weak.

## Shadow Kernel Deltas

Each delta candidate contains:

- `parameter`
- `old_value`
- `proposed_value`
- `delta`
- `evidence`
- `confidence`
- `rollback_id`
- `applied=false`

Examples:

```text
unsupported_memory_detail
  lower memory_trust
  raise correction_sensitivity
  raise caution
```

```text
Stage142 suppressed_duplicate or high packet waste
  raise novelty_threshold
  raise continuation_threshold
  lower verbosity_bias
```

```text
ungrounded_tool_claim
  raise tool_preference
  raise risk_aversion
  raise caution
```

```text
weak context sufficiency
  raise clarification_threshold
  raise caution
```

Clean grounded turns can produce low prediction error and no delta candidates.

## Runtime Integration

`CodexCliProcessor` stores:

```text
ReplyPlan.debug["stage145_outcome_appraisal"]
ReplyPlan.debug["stage145_reaction_kernel_shadow"]
```

`HoloReplyService` rebuilds Stage145 after final Stage139-144 metadata is available, then propagates both reports into:

- reply JSON
- outgoing metadata
- archive/observe metadata
- Stage135 topology when a topology is built

Stage135 can render a compact `reaction_kernel_shadow` node with:

- `reaction_kernel_node_count`
- `reaction_kernel_prediction_error`
- `reaction_kernel_delta_count`
- `reaction_kernel_shadow_only`

## Constraints Preserved

- Shadow-only by default.
- No durable policy mutation.
- No model-weight learning.
- No self-memory write.
- No provider calls.
- No tool execution.
- No transport changes.
- No WeChat start.
- No second loop.
- Stage139, Stage140, Stage141, Stage142, Stage143, and Stage144 remain authoritative for their own gates and reports.

## Next Stage

Stage146 should use Stage145 reports to build a replayable reaction-kernel calibration evaluator. It should compare predicted deltas against later user correction or success signals before any live application path is considered.
