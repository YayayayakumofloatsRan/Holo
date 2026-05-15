# Stage82 Biomimetic Gain Control

## What Stage82 Adds

Stage82 executes the remaining direct falsification control from the Stage78-81
matrix: neuromodulatory gain clamp over real-provider Stage59/60-gated trace
artifacts. It does not run a new provider campaign by itself. Its purpose is to
test whether the neuromodulatory adaptive-gain mapping is more than a passive
label by clamping dopamine, norepinephrine, acetylcholine, and serotonin to a
neutral value while preserving salience, consolidation priority, replay phase,
recall budget, prompt-cost proxy, and boundary proxy.

The implementation is `holo_host/biomimetic_gain_control.py` with CLI:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-gain-control --theory-json artifacts\stage78\stage78_theory_correspondence.json --precision-control-json artifacts\stage81\stage81_biomimetic_precision_control.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage82\stage82_biomimetic_gain_control.html
```

## Control Matrix

| control | status | current evidence |
| --- | --- | --- |
| GNW ignition-null | `supported_direct_control` | Stage79 found prompt-cost-matched ignition-null lowers flow-to-reply coupling in both Stage77 model cells while preserving correction proxy. |
| Hippocampal/CLS marker removal | `supported_direct_control` | Stage80 found marker removal collapses delayed correction survival in both Stage77 model cells while prompt cost and boundary stay matched. |
| Predictive-processing neutral salience | `supported_direct_control` | Stage81 found neutral salience lowers delayed correction survival in both Stage77 model cells while replay phase, prompt cost, and boundary stay matched. |
| Neuromodulatory gain clamp | `supported_direct_control` | Stage82 finds neutral gain clamp lowers neuromodulator coupling in both Stage77 model cells while replay/correction remains above threshold and phase, prompt cost, and boundary stay matched. |

## Current Evidence

Command:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-gain-control --theory-json artifacts\stage78\stage78_theory_correspondence.json --precision-control-json artifacts\stage81\stage81_biomimetic_precision_control.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage82\stage82_biomimetic_gain_control.html
```

Result:

- `stage=stage82-biomimetic-gain-control`
- `decision=gain_clamp_supports_neuromodulatory_adaptive_gain_control`
- `supported_scope=bounded_neuromodulatory_gain_control`
- `control_count=1`
- `executed_control_count=1`
- `pending_control_count=0`
- `trace_report_count=2`
- `precision_control_precondition_supported=true`
- `active_replay_correction_intact=true`
- `gain_clamp_reduces_neuromodulator_coupling=true`
- `gain_clamp_preserves_replay_phase=true`
- `mean_gain_clamp_neuromodulator_coupling_delta=-0.321447`
- `mean_gain_clamp_correction_survival_delta=-0.054007`
- `mean_gain_clamp_correction_survival_proxy=0.820294`
- `mean_gain_clamp_prompt_cost_delta=0.0`
- `mean_gain_clamp_reactivation_phase_delta=0.0`
- `real_provider_trace=true`
- `theory_language_bounded=true`
- `direct_controls_incomplete=false`
- `do_not_claim_real_consciousness=true`

The executed gain-clamp control is replicated in both Stage77 model cells:

- `01_deepseek-v4-pro`: baseline neuromodulator coupling `0.818657`, gain-clamped coupling `0.5`, coupling delta `-0.318657`, baseline correction `0.874301`, gain-clamped correction `0.820294`, correction delta `-0.054007`, prompt-cost delta `0.0`, reactivation-phase delta `0.0`, boundary delta `0.0`, delayed probes `11`
- `02_deepseek-v4-flash`: baseline neuromodulator coupling `0.824236`, gain-clamped coupling `0.5`, coupling delta `-0.324236`, baseline correction `0.874301`, gain-clamped correction `0.820294`, correction delta `-0.054007`, prompt-cost delta `0.0`, reactivation-phase delta `0.0`, boundary delta `0.0`, delayed probes `11`

## Interpretation

Stage82 closes the final pending theory-control row from Stage78. The strongest
bounded claim is now:

```text
Holo's neuromodulatory adaptive-gain mapping is sensitive to a direct gain
clamp in matched real-provider traces. Clamping dopamine, norepinephrine,
acetylcholine, and serotonin lowers the neuromodulator-coupling proxy in both
Stage77 cells while replay phase, prompt-cost proxy, boundary proxy, and
above-threshold correction survival are preserved.
```

The result remains bounded:

```text
Stage82 supports an adaptive-gain coupling proxy over real-provider traces. It
is not biological neuromodulation proof, not evidence of subjective
consciousness, and not a claim that Holo has neural tissue-like dynamics.
```

## Next Gate

Stage83 should move from mechanism discovery to publication packaging and
independent replication summary:

- assemble the Stage79-82 direct-control matrix into paper-ready tables and
  figures
- rerun a focused independent control summary or an additional Stage60-gated
  provider cell only if it directly tests replication of the completed controls
- keep GNW language partial because flow-coupling remains within-model/cell
  unstable
- keep all biological and consciousness claims bounded to operational proxies

## Boundary

Stage82 is read-only over existing evidence:

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
