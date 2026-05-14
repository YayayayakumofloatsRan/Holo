# Stage72 Correction Reactivation Marker Plan

## Goal

Close the provider-replay gap exposed by Stage71 by making explicit user
corrections enter Holo's biomimetic memory schedule as a replay marker.

## Trigger

Stage71 showed:

- surrogate full-lab result: strong support
- real DeepSeek provider replication: partial support
- provider hippocampal-reactivation delta stayed below threshold

## Implementation

Add a bounded `correction_reactivation_marker` path:

1. Detect strong correction cues in current query or latest user intent.
2. Add marker to hippocampal index.
3. Add `correction_reactivation` to salience sources.
4. Add marker to consolidation targets.
5. Include marker in lifecycle replay sources.
6. Let consciousness flow use the marker as memory-reactivation input.

## Acceptance

Tests must prove:

- the marker enters hippocampal dynamic lines
- salience and recall budget increase
- consolidation targets include the marker
- lifecycle replay sources include the marker
- consciousness flow chooses `memory_reactivation`
- self-memory writes remain disabled

## Result

DeepSeek provider trace after Stage72:

- `collected_turn_count=30`
- `observed_total_tokens=135043`
- `max_latency_ms=617411.46`
- baseline `hippocampal_reactivation=0.918328`
- baseline `correction_survival_proxy=0.830654`
- `decision=partial_support_real_provider`
- `boundary_violation_delta=0.0`

Provider comparison:

- baseline `hippocampal_reactivation`: `0.897044 -> 0.918328`
- baseline `correction_survival_proxy`: `0.801491 -> 0.830654`

Conclusion: mechanism improved the absolute provider baseline, but Stage71's
counterfactual decision remains partial because the boost condition now has less
remaining headroom. Stage73 should split absolute improvement from residual
counterfactual headroom.

## Verification

Completed:

```powershell
python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_bionic_memory_lifecycle.py tests\test_bionic_consciousness_flow.py
python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_bionic_memory_lifecycle.py tests\test_bionic_consciousness_flow.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py
python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\bionic_memory_lifecycle.py holo_host\bionic_consciousness_flow.py holo_host\context_scheduler.py holo_host\bionic_boundary_stress.py
git diff --check
```
