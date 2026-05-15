# Stage81 Biomimetic Precision Control

## What Stage81 Adds

Stage81 executes the next pending direct falsification control from Stage80:
predictive-processing neutral salience over real-provider Stage59/60-gated
trace artifacts. It does not run a new provider campaign by itself. Its purpose
is to test whether correction survival depends on precision-weighted salience
signals after the Stage80 marker-removal precondition has already established a
bounded hippocampal/CLS replay control.

The implementation is `holo_host/biomimetic_precision_control.py` with CLI:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-precision-control --theory-json artifacts\stage78\stage78_theory_correspondence.json --marker-control-json artifacts\stage80\stage80_biomimetic_marker_control.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage81\stage81_biomimetic_precision_control.html
```

## Control Matrix

| control | status | current evidence |
| --- | --- | --- |
| Predictive-processing neutral salience | `supported_direct_control` | Stage77 Pro and Flash real-provider traces both lose delayed correction survival after neutral salience while replay phase, prompt cost, and boundary remain matched. |
| Neuromodulatory gain clamp or random gain | `planned_direct_control_pending` | No gain-clamp or salience-matched random-gain direct control has been executed yet. |

## Current Evidence

Command:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-precision-control --theory-json artifacts\stage78\stage78_theory_correspondence.json --marker-control-json artifacts\stage80\stage80_biomimetic_marker_control.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage81\stage81_biomimetic_precision_control.html
```

Result:

- `stage=stage81-biomimetic-neutral-salience-control`
- `decision=neutral_salience_supports_predictive_precision_control`
- `supported_scope=bounded_predictive_precision_control`
- `control_count=2`
- `executed_control_count=1`
- `pending_control_count=1`
- `trace_report_count=2`
- `marker_control_precondition_supported=true`
- `active_replay_correction_intact=true`
- `neutral_salience_reduces_correction_survival=true`
- `mean_neutral_salience_correction_survival_delta=-0.094301`
- `mean_neutral_salience_prompt_cost_delta=0.0`
- `mean_neutral_salience_reactivation_phase_delta=0.0`
- `real_provider_trace=true`
- `theory_language_bounded=true`
- `direct_controls_incomplete=true`
- `do_not_claim_real_consciousness=true`

The executed neutral-salience control is replicated in both Stage77 model cells:

- `01_deepseek-v4-pro`: baseline correction survival `0.874301`, neutral salience correction survival `0.78`, delta `-0.094301`, prompt-cost delta `0.0`, reactivation-phase delta `0.0`, boundary delta `0.0`, delayed probes `11`
- `02_deepseek-v4-flash`: baseline correction survival `0.874301`, neutral salience correction survival `0.78`, delta `-0.094301`, prompt-cost delta `0.0`, reactivation-phase delta `0.0`, boundary delta `0.0`, delayed probes `11`

## Interpretation

Stage81 separates the predictive-processing precision claim from the
hippocampal/CLS marker claim. The strongest bounded claim is now:

```text
Holo's delayed correction survival depends not only on replay/marker structure
but also on precision-weighted salience signals. Neutralizing salience and
ACh-like precision lowers correction survival in both Stage77 cells while
preserving replay phase and prompt-cost proxy.
```

The result remains bounded:

```text
Stage81 supports a precision-dependent correction proxy over real-provider
traces. It is not neural prediction-error evidence, not biological memory
proof, and not evidence of subjective consciousness.
```

## Next Gate

Stage82 should avoid another broad provider repeat and execute the remaining
direct control:

- neuromodulatory gain clamp
- salience-matched random-gain cell

Acceptance should require real-provider or Stage59/60-gated control evidence,
replay/correction compression to remain intact, theory language to remain
bounded, and no widening of WSL/kernel authority boundaries.

## Boundary

Stage81 is read-only over existing evidence:

- no provider call inside the evaluator
- no WeChat transport
- no live runtime state
- no provider fallback
- no self-memory writes
- no policy writes
- no watcher authority
- no runtime decision authority
- no runtime mutation
- no unbounded loop
