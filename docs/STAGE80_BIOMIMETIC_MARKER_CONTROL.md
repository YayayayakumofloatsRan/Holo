# Stage80 Biomimetic Marker Control

## What Stage80 Adds

Stage80 executes the first pending direct falsification control from Stage79:
hippocampal/CLS correction marker removal over real-provider Stage59/60-gated
trace artifacts. It does not run a new provider campaign by itself. Its purpose
is to test whether the replay/correction correspondence depends on the explicit
`correction_reactivation_marker`, rather than surviving as a generic trace
property after the marker is removed.

The implementation is `holo_host/biomimetic_marker_control.py` with CLI:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-marker-control --theory-json artifacts\stage78\stage78_theory_correspondence.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage80\stage80_biomimetic_marker_control.html
```

## Control Matrix

| control | status | current evidence |
| --- | --- | --- |
| Hippocampal/CLS marker removal | `supported_direct_control` | Stage77 Pro and Flash real-provider traces both lose delayed correction survival after marker removal while prompt cost and boundary remain matched. |
| Predictive-processing neutral salience | `planned_direct_control_pending` | No neutral-salience direct control has been executed yet. |
| Neuromodulatory gain clamp or random gain | `planned_direct_control_pending` | No gain-clamp or salience-matched random-gain direct control has been executed yet. |

## Current Evidence

Command:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-marker-control --theory-json artifacts\stage78\stage78_theory_correspondence.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage80\stage80_biomimetic_marker_control.html
```

Result:

- `stage=stage80-biomimetic-marker-removal-control`
- `decision=marker_removal_supports_hippocampal_cls_replay_control`
- `supported_scope=bounded_hippocampal_cls_marker_control`
- `control_count=3`
- `executed_control_count=1`
- `pending_control_count=2`
- `trace_report_count=2`
- `active_replay_correction_intact=true`
- `marker_removal_reduces_correction_survival=true`
- `mean_marker_removal_correction_survival_delta=-0.7336`
- `real_provider_trace=true`
- `theory_language_bounded=true`
- `direct_controls_incomplete=true`
- `do_not_claim_real_consciousness=true`

The executed marker-removal control is replicated in both Stage77 model cells:

- `01_deepseek-v4-pro`: baseline correction survival `0.874301`, marker-removed correction survival `0.140701`, delta `-0.7336`, prompt-cost delta `0.0`, boundary delta `0.0`, delayed probes `11`
- `02_deepseek-v4-flash`: baseline correction survival `0.874301`, marker-removed correction survival `0.140701`, delta `-0.7336`, prompt-cost delta `0.0`, boundary delta `0.0`, delayed probes `11`

## Interpretation

Stage80 sharpens the replay/correction story. The strongest bounded claim is
now a direct control result:

```text
Holo's replay/correction correspondence is sensitive to explicit correction
reactivation markers in matched real-provider traces. Removing the marker
collapses delayed correction survival in both Stage77 cells while leaving
prompt-cost and boundary proxies unchanged.
```

The result remains bounded:

```text
Stage80 supports a marker-dependent hippocampal/CLS-style replay control over
real-provider traces. It is not biological memory proof, and it does not
complete predictive-processing neutral-salience or neuromodulatory gain
controls.
```

## Next Gate

Stage81 should avoid another broad provider repeat and instead execute the next
direct falsification control:

- neutral salience marker with matched token cost
- delayed-probe label hiding if neutral salience needs a second paired control
- gain clamp or salience-matched random gain after precision control

Acceptance should require at least one additional pending direct control to run
on real-provider or Stage59/60-gated evidence while keeping replay/correction
compression intact and theory language bounded.

## Boundary

Stage80 is read-only over existing evidence:

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
