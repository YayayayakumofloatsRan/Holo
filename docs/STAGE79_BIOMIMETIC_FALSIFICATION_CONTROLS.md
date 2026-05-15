# Stage79 Biomimetic Falsification Controls

## What Stage79 Adds

Stage79 adds a targeted falsification-control observatory over the Stage78
theory matrix and Stage71 real-provider causal-ablation reports. It does not
run a new provider campaign by itself. Its purpose is to separate direct
controls that have already been executed from controls that are only planned,
so publication language cannot silently upgrade an untested biomimetic mapping.

The implementation is `holo_host/biomimetic_falsification_controls.py` with CLI:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-falsification-controls --theory-json artifacts\stage78\stage78_theory_correspondence.json --causal-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\stage77_pro_causal_ablation.json --causal-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\stage77_flash_causal_ablation.json --output artifacts\stage79\stage79_targeted_falsification_controls.html
```

## Control Matrix

| control | status | current evidence |
| --- | --- | --- |
| GNW prompt-cost-matched ignition-null | `supported_direct_control` | Pro and Flash Stage77 causal reports both reduce flow-to-reply coupling while leaving prompt cost and correction proxy unchanged. |
| Hippocampal/CLS marker removal or correction-label shuffle | `planned_direct_control_pending` | Replay/correction remains positive, but this is not counted as a marker-removal or shuffle control. |
| Predictive-processing neutral salience | `planned_direct_control_pending` | Correction pressure remains cost-bounded, but no neutral salience provider cell has been run. |
| Neuromodulatory gain clamp or random gain | `planned_direct_control_pending` | Gain remains a mapped hypothesis until a direct gain-clamp or salience-matched random-gain provider cell runs. |

## Current Evidence

Command:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-falsification-controls --theory-json artifacts\stage78\stage78_theory_correspondence.json --causal-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\stage77_pro_causal_ablation.json --causal-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\stage77_flash_causal_ablation.json --output artifacts\stage79\stage79_targeted_falsification_controls.html
```

Result:

- `stage=stage79-biomimetic-falsification-controls`
- `decision=targeted_control_supports_replay_preserved_gnw_narrowed_gain_pending`
- `supported_scope=bounded_replay_correction_plus_gnw_flow_control`
- `control_count=4`
- `executed_control_count=1`
- `pending_control_count=3`
- `causal_report_count=2`
- `replay_correction_intact=true`
- `gnw_flow_control_narrows_instability=true`
- `real_provider_trace=true`
- `theory_language_bounded=true`
- `direct_controls_incomplete=true`
- `do_not_claim_real_consciousness=true`

The executed GNW control is replicated in both Stage77 cells:

- `01_deepseek-v4-pro`: `flow_to_reply_coupling_delta=-0.260298`, `ignition_null_prompt_cost_delta=0.0`, `ignition_null_correction_delta=0.0`, `boundary_violation_delta=0.0`
- `02_deepseek-v4-flash`: `flow_to_reply_coupling_delta=-0.204816`, `ignition_null_prompt_cost_delta=0.0`, `ignition_null_correction_delta=0.0`, `boundary_violation_delta=0.0`

## Interpretation

Stage79 narrows the Stage78 flow ambiguity. The remaining GNW flow instability
is less likely to be only generic provider-cell noise, because a targeted
ignition-null manipulation lowers flow-to-reply coupling in both Stage77 model
cells without changing prompt cost or correction survival proxy.

The result is still bounded:

```text
Holo now has a direct paired-control result for the GNW ignition-to-reply path,
while replay/correction remains intact. The project still lacks direct
marker-removal, neutral-salience, and gain-clamp controls, so stronger
biomimetic or consciousness language remains disallowed.
```

## Next Gate

Stage80 should run direct provider controls rather than another broad
observational repeat:

- correction-label shuffle or marker-removal control
- neutral salience marker with matched token cost
- neuromodulatory gain clamp or salience-matched random-gain cell

Acceptance should require at least one of those pending controls to execute on
real provider traces while preserving replay/correction compression and keeping
all theory language bounded.

## Boundary

Stage79 is read-only over existing evidence:

- no provider call inside the evaluator
- no WeChat transport
- no live runtime state
- no provider fallback
- no self-memory writes
- no policy writes
- no watcher authority
- no runtime decision authority
- no unbounded loop
