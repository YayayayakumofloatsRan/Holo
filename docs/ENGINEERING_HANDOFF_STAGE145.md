# Engineering Handoff Stage145

Date: 2026-05-24

## Summary

Stage145 adds deterministic prediction-error appraisal and a shadow reaction-kernel parameter layer. Holo now reports what the turn appeared to need, what outcome would have been best, what grounding or novelty outcome was observed, the resulting prediction error, and which local reaction parameters would shift under a future calibration regime.

Stage145 is shadow-only. It does not apply deltas, mutate durable policy, learn model weights, write self-memory, call providers, execute tools, change transport behavior, start WeChat, or add a second loop.

## Files Changed

- `holo_host/stage145_reaction_kernel.py`
  - Adds `holo.stage145.outcome_appraisal.v1`.
  - Adds `holo.stage145.reaction_kernel_shadow.v1`.
  - Builds deterministic prediction-error reports from Stage139-144 evidence.
  - Produces bounded reaction-kernel delta candidates with `applied=false`.

- `holo_host/processors.py`
  - Stores Stage145 reports in `ReplyPlan.debug` for both fast-only and fast+deep paths.
  - Passes Stage145 reports into Stage135 topology construction.

- `holo_host/reply_api.py`
  - Rebuilds Stage145 reports after final Stage139/140/141/142/143/144 metadata is available.
  - Propagates both reports into reply JSON, outgoing metadata, and archive/observe metadata.

- `holo_host/stage135_i_state_topology.py`
  - Adds optional `reaction_kernel_shadow` node and compact metrics.

- `tests/test_stage145_reaction_kernel.py`
  - Covers unsupported memory detail, duplicate continuation suppression, ungrounded tool claims, clean grounded turns, shadow-only deltas, reply/archive propagation, Stage135 topology, and no private memory writes from the direct builder.

- `tests/test_stage135_i_state_topology.py`
  - Verifies the reaction-kernel topology node and processor debug propagation.

- `docs/STAGE145_PREDICTIVE_REACTION_KERNEL.md`
- `docs/ENGINEERING_HANDOFF_STAGE145.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schemas

```text
holo.stage145.outcome_appraisal.v1
holo.stage145.reaction_kernel_shadow.v1
```

## Runtime Propagation

Stage145 is exposed as:

- `ReplyPlan.debug["stage145_outcome_appraisal"]`
- `ReplyPlan.debug["stage145_reaction_kernel_shadow"]`
- `result["stage145_outcome_appraisal"]`
- `result["stage145_reaction_kernel_shadow"]`
- `result["stage145_prediction_error"]`
- `result["stage145_kernel_delta_count"]`
- `result["stage145_shadow_only"]`
- outgoing metadata
- archive/observe metadata
- optional Stage135 `reaction_kernel_shadow` node

## Examples

Unsupported memory detail:

```text
memory_alignment=unsupported_memory_detail
prediction_error rises
memory_trust decreases
correction_sensitivity and caution increase
```

Duplicate A'':

```text
stage142=suppressed_duplicate
packet_waste high
novelty_threshold and continuation_threshold increase
verbosity_bias decreases
```

Ungrounded tool claim:

```text
tool_grounding=ungrounded_tool_claim
tool_preference and risk_aversion increase
caution increases
```

Clean grounded answer:

```text
tool_grounding=grounded
memory_alignment=aligned
stage142=passed
packet_waste low
prediction_error stays low and no delta candidate is emitted
```

## Verification

Targeted Stage145/144:

```powershell
python -m pytest tests\test_stage145_reaction_kernel.py tests\test_stage144_context_economy.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage145-targeted
```

Observed:

```text
16 passed in 0.47s
```

Runtime:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage145-runtime
```

Observed:

```text
89 passed in 22.87s
```

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Observed:

```text
531 passed in 64.12s (0:01:04)
```

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
```

Observed:

```text
Public release hygiene passed: no private profile, memory, runtime, artifact, live transport path, or blocked persona marker is tracked.
```

Diff check:

```powershell
git diff --check
```

Observed:

```text
passed; Git printed line-ending normalization warnings only
```

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
- Stage139-144 reports remain authoritative.

## Next Suggested Stage

Stage146 should build a replayable reaction-kernel calibration evaluator. It should compare Stage145 shadow deltas against later user correction, duplicate suppression, tool success, and memory alignment outcomes before any live application gate is considered.
