# Stage72 Correction Reactivation Marker

## What Stage72 Adds

Stage72 closes the first provider-replay gap found by Stage71.

Stage71 showed:

- Stage69 surrogate counterfactuals strongly supported correction-triggered replay.
- A real DeepSeek provider replication only partially supported the mechanism:
  correction survival and ignition coupling moved correctly, but the
  hippocampal-reactivation delta remained below the complete-support threshold.

Stage72 adds a real mechanism path instead of another observatory:

- explicit correction text becomes a `correction_reactivation_marker`
- the marker enters the hippocampal index
- salience gate receives `correction_reactivation`
- consolidation targets include `correction_reactivation_marker`
- lifecycle replay sources include the marker and recent dialogue window
- consciousness flow can make the marker the memory-reactivation phase input

The implementation remains prompt/diagnostic only. It does not write self-memory,
does not start WeChat, does not mutate policy, and does not add a decision layer.

## Runtime Surfaces

Changed:

- `holo_host/bionic_memory_scheduler.py`
- `holo_host/bionic_memory_lifecycle.py`

Regression tests:

- `tests/test_bionic_memory_scheduler.py`
- `tests/test_bionic_memory_lifecycle.py`
- `tests/test_bionic_consciousness_flow.py`

## Mechanism

When the current query or latest user intent contains a strong correction cue
such as `Correction:`, `corrected`, `replaced`, `replaces`, or a `not ... anymore`
contrast, the scheduler creates:

```text
correction_reactivation_marker=<bounded current correction text>
```

That marker is treated as protected dynamic memory. It is allowed to enter:

- `hippocampal_index.dynamic_lines`
- `prompt_dynamic_lines`
- `salience_gate.sources`
- `consolidation_targets.targets`
- lifecycle `replay_plan.sources`
- consciousness-flow `memory_reactivation`

The marker does not authorize self-memory writes. It only raises current-turn
replay pressure and provider-visible dynamic context.

## DeepSeek Provider Result

Stage72 provider trace:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --runs 3 --turns 10 --max-total-tokens 180000 --provider-hint deepseek --model deepseek-v4-pro --lane kernel_xhigh --max-output-tokens 180 --output artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.html
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --output artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.html
```

Trace result:

- `status=complete`
- `collected_turn_count=30`
- `real_provider_trace=true`
- `observed_total_tokens=135043`
- `stopped_reason=completed`
- `do_not_claim_real_manifold=true`
- `max_latency_ms=617411.46`

Stage71 evaluator over the Stage72 trace returned:

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.011205`
- `correction_survival_proxy_delta=0.048457`
- `flow_to_reply_coupling_delta=-0.342426`
- `prompt_cost_delta=0.033333`
- `boundary_violation_delta=0.0`

Absolute provider comparison against the previous Stage71 real trace:

| metric | Stage71 provider trace | Stage72 provider trace | direction |
| --- | ---: | ---: | --- |
| baseline `hippocampal_reactivation` | `0.897044` | `0.918328` | improved |
| baseline `correction_survival_proxy` | `0.801491` | `0.830654` | improved |
| `flow_to_reply_coupling_delta` | `-0.438947` | `-0.342426` | still strongly negative under ablation |
| `boundary_violation_delta` | `0.0` | `0.0` | stable |

Interpretation:

Stage72 improves the absolute real-provider baseline but does not yet turn the
Stage71 counterfactual decision into full support. The next scientific cut should
separate absolute provider improvement from counterfactual headroom, then add a
longer trace or repeated cells to reduce the 30-turn geometry/attractor weakness.

## Verification

Completed locally:

```powershell
python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_bionic_memory_lifecycle.py tests\test_bionic_consciousness_flow.py
python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_bionic_memory_lifecycle.py tests\test_bionic_consciousness_flow.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py
python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\bionic_memory_lifecycle.py holo_host\bionic_consciousness_flow.py holo_host\context_scheduler.py holo_host\bionic_boundary_stress.py
git diff --check
```
