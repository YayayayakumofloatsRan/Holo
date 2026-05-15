# Stage76 Model-Family Stability

## What Stage76 Adds

Stage76 tests whether the Stage74/75 replay-correction headroom compression
survives DeepSeek model-family variation.

It adds a read-only model-family stability observatory:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-model-family-stability --model-progress deepseek-v4-pro=artifacts\stage74\stage74_provider_progress_vs_stage72.json --model-progress deepseek-v4-pro=artifacts\stage75\stage75_provider_progress_vs_stage72.json --model-progress deepseek-v4-pro=artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\stage76_pro_provider_progress_vs_stage72.json --model-progress deepseek-v4-flash=artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\stage76_flash_provider_progress_vs_stage72.json --output artifacts\stage76\stage76_model_family_20260515\stage76_model_family_stability.html
```

The observatory consumes model-labeled Stage73 provider-progress reports. It
does not call a provider and does not change runtime behavior.

## Model-Family Provider Campaign

Run:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --execute --campaign-id stage76_model_family_20260515 --models deepseek-v4-pro,deepseek-v4-flash --runs-per-model 3 --turns 14 --max-total-tokens-per-cell 260000 --provider-hint deepseek --lane auto --max-output-tokens 180 --output-root artifacts\stage76\stage76_model_family_20260515
```

Result:

- `status=complete`
- `planned_cell_count=2`
- `planned_total_turns=84`
- `real_provider_cell_count=2`
- `collected_turn_count=84`
- `observed_total_tokens=395762`
- `top_model=deepseek-v4-flash`
- `top_score=0.9019`
- `do_not_claim_major_breakthrough=true`

Per cell:

- `deepseek-v4-pro`: `collected_turn_count=42`, `observed_total_tokens=196741`
- `deepseek-v4-flash`: `collected_turn_count=42`, `observed_total_tokens=199021`

## Stage71 Results

Pro:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\provider_trace.json --output artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\stage76_pro_causal_ablation.html
```

Result:

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.010344`
- `correction_survival_proxy_delta=0.042215`
- `flow_to_reply_coupling_delta=-0.308315`
- `prompt_cost_delta=0.041666`
- `boundary_violation_delta=0.0`
- `surrogate_only=false`
- `causal_language_bounded=true`

Flash:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\stage76_flash_causal_ablation.html
```

Result:

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.010408`
- `correction_survival_proxy_delta=0.042215`
- `flow_to_reply_coupling_delta=-0.136848`
- `prompt_cost_delta=0.041666`
- `boundary_violation_delta=0.0`
- `surrogate_only=false`
- `causal_language_bounded=true`

## Stage73 Results Against Stage72

Pro:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.json --after-json artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\stage76_pro_causal_ablation.json --before-trace-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --after-trace-json artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\provider_trace.json --output artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\stage76_pro_provider_progress_vs_stage72.html
```

Result:

- `decision=absolute_improved_residual_partial`
- baseline `hippocampal_reactivation_delta=0.018121`
- baseline `correction_survival_proxy_delta=0.043647`
- baseline `biomimetic_score_delta=0.012356`
- residual `hippocampal_reactivation_headroom_change=-0.000861`
- residual `correction_survival_headroom_change=-0.006242`
- `flow_to_reply_coupling_loss_reduction=0.034111`
- `after_latency_outlier=false`
- `after_observed_total_tokens=196741`
- `real_provider_trace=true`

Flash:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.json --after-json artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\stage76_flash_causal_ablation.json --before-trace-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --after-trace-json artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\stage76_flash_provider_progress_vs_stage72.html
```

Result:

- `decision=absolute_improved_residual_partial`
- baseline `hippocampal_reactivation_delta=0.018057`
- baseline `correction_survival_proxy_delta=0.043647`
- baseline `biomimetic_score_delta=0.022271`
- residual `hippocampal_reactivation_headroom_change=-0.000797`
- residual `correction_survival_headroom_change=-0.006242`
- `flow_to_reply_coupling_loss_reduction=0.205578`
- `after_latency_outlier=false`
- `after_observed_total_tokens=199021`
- `real_provider_trace=true`

## Stage75-Style Stability Result

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-replication-stability --progress-json artifacts\stage74\stage74_provider_progress_vs_stage72.json --progress-json artifacts\stage75\stage75_provider_progress_vs_stage72.json --progress-json artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\stage76_pro_provider_progress_vs_stage72.json --progress-json artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\stage76_flash_provider_progress_vs_stage72.json --output artifacts\stage76\stage76_model_family_20260515\stage76_replication_stability.html
```

Result:

- `decision=replicated_replay_correction_partial_flow`
- `replicated_scope=replay_correction_only`
- `cell_count=4`
- `real_provider_cell_count=4`
- `absolute_improved_cell_count=4`
- `replay_correction_compression_cell_count=4`
- `flow_loss_reduction_cell_count=3`
- `latency_outlier_cell_count=0`
- mean `hippocampal_reactivation_headroom_change=-0.000646`
- mean `correction_survival_headroom_change=-0.004938`
- mean `flow_to_reply_coupling_loss_reduction=0.057628`
- `observed_total_tokens=782380`

## Stage76 Model-Family Result

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-model-family-stability --model-progress deepseek-v4-pro=artifacts\stage74\stage74_provider_progress_vs_stage72.json --model-progress deepseek-v4-pro=artifacts\stage75\stage75_provider_progress_vs_stage72.json --model-progress deepseek-v4-pro=artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\stage76_pro_provider_progress_vs_stage72.json --model-progress deepseek-v4-flash=artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\stage76_flash_provider_progress_vs_stage72.json --output artifacts\stage76\stage76_model_family_20260515\stage76_model_family_stability.html
```

Result:

- `decision=model_family_replay_correction_supported_flow_cell_unstable`
- `supported_scope=replay_correction_with_flow_cell_instability`
- `model_count=2`
- `cell_count=4`
- `real_provider_cell_count=4`
- `replay_correction_compression_cell_count=4`
- `flow_loss_reduction_cell_count=3`
- `flow_instability_assessment=within_model_replication_unstable_not_model_specific`
- mean `hippocampal_reactivation_headroom_change=-0.000646`
- mean `correction_survival_headroom_change=-0.004938`
- mean `flow_to_reply_coupling_loss_reduction=0.057628`
- `observed_total_tokens=782380`
- `real_provider_trace=true`

Per model:

- `deepseek-v4-pro`: `3` real cells, `3/3` replay-correction compression,
  `2/3` flow-loss reduction, mean flow reduction `0.008311`, observed tokens
  `583359`
- `deepseek-v4-flash`: `1` real cell, `1/1` replay-correction compression,
  `1/1` flow-loss reduction, mean flow reduction `0.205578`, observed tokens
  `199021`

Interpretation:

Replay/correction headroom compression survives model-family variation. The
flow-coupling instability is not cleanly model-specific: Pro can reduce flow
loss in Stage74 and Stage76, Flash also reduces it, but the independent Stage75
Pro cell did not. The current classification is therefore within-model/cell
replication instability, not a DeepSeek V4 Pro versus Flash split and not a
mechanism-level impossibility.

The clean Stage76 claim is:

```text
Replay/correction residual headroom compression survived repeated real-provider
model-family testing across DeepSeek V4 Pro and Flash; flow-coupling compression
remains cell unstable rather than clearly model-specific.
```

Do not describe Stage76 as full mechanism support or evidence of real
consciousness.

## Boundary

Stage76 preserves existing authority boundaries:

- provider calls happen only through the Stage60 operator-gated campaign path
- Stage76 observatory is read-only over Stage73 reports
- no WeChat transport
- no live runtime state use
- no provider fallback
- no self-memory writes
- no policy writes
- no watcher authority
- no runtime decision authority
- no unbounded loop

## Verification

Completed on `2026-05-15`:

```powershell
python -m pytest tests\test_stage76_biomimetic_model_family_stability.py tests\test_stage75_biomimetic_replication_stability.py tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python -m py_compile holo_host\biomimetic_model_family_stability.py holo_host\biomimetic_replication_stability.py holo_host\biomimetic_provider_progress.py holo_host\cli.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

- related Stage70/71/73/75/76 regression passed with `16` tests.
- compile passed.
- full suite passed with `495` tests.
- public release hygiene passed.
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings.

## Next Gate

Stage77 should stop spending tokens on more observational repeats until the
flow path receives a mechanism change. The next useful experiment is an explicit
global-workspace ignition-to-reply coupling intervention that can be tested by
the same Stage71/73/76 chain.
