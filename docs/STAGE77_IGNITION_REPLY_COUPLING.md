# Stage77 Ignition-to-Reply Coupling

## What Stage77 Adds

Stage77 converts `global_workspace_ignition` from a read-only observational
score into an explicit bounded prompt-level mechanism.

The change stays inside the existing WSL subject runtime path:

- `bionic_consciousness_flow` now emits structured
  `global_workspace_ignition` and `ignition_to_reply_coupling`
- Stage52 prompt fusion carries those lines into the existing
  `Bionic Dynamic Frame`
- Stage70/71 observatories prefer explicit Stage77 mechanism fields when they
  are present, while remaining backward-compatible for older artifacts

Stage77 does not add watcher authority, runtime authority, WeChat transport,
self-memory writes, or policy writes.

## Mechanism

The mechanism uses existing bounded inputs only:

- scheduler salience gate
- lifecycle consolidation priority
- correction-reactivation marker pressure
- selected action
- uncertainty level

Under correction pressure, the reply target becomes
`memory_reactivation_first` and the prompt carries an explicit
`ignition_to_reply_coupling` line into the provider-facing dynamic frame.

## Local Verification

Completed on `2026-05-15`:

```powershell
python -m pytest tests\test_bionic_consciousness_flow.py tests\test_context_scheduler.py tests\test_stage70_biomimetic_consciousness_observatory.py tests\test_stage71_biomimetic_causal_ablation.py -q
python -m pytest tests\test_bionic_memory_scheduler.py tests\test_bionic_memory_lifecycle.py tests\test_stage73_biomimetic_provider_progress.py tests\test_stage75_biomimetic_replication_stability.py tests\test_stage76_biomimetic_model_family_stability.py -q
python -m py_compile holo_host\bionic_consciousness_flow.py holo_host\bionic_memory_scheduler.py holo_host\biomimetic_consciousness_observatory.py holo_host\biomimetic_causal_ablation.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

- focused Stage77 regression passed with `22` tests
- scheduler/progress/stability regression passed with `20` tests
- compile passed
- full suite passed with `498` tests
- public release hygiene passed
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings

## Real-Provider Campaign

Run:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --execute --campaign-id stage77_ignition_reply_20260515 --models deepseek-v4-pro,deepseek-v4-flash --runs-per-model 3 --turns 14 --max-total-tokens-per-cell 260000 --provider-hint deepseek --lane auto --max-output-tokens 180 --output-root artifacts\stage77\stage77_ignition_reply_20260515
```

Result:

- `status=complete`
- `planned_total_turns=84`
- `real_provider_cell_count=2`
- `collected_turn_count=84`
- `observed_total_tokens=393716`
- `top_model=deepseek-v4-flash`
- `top_score=0.9046`
- `do_not_claim_major_breakthrough=true`

## Stage71 Results

Pro:

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.010408`
- `correction_survival_proxy_delta=0.042215`
- `flow_to_reply_coupling_delta=-0.260298`
- `boundary_violation_delta=0.0`

Flash:

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.010408`
- `correction_survival_proxy_delta=0.042215`
- `flow_to_reply_coupling_delta=-0.204816`
- `boundary_violation_delta=0.0`

## Stage73 Results Against Stage72

Pro:

- `decision=absolute_improved_residual_partial`
- baseline `hippocampal_reactivation_delta=0.017593`
- baseline `correction_survival_proxy_delta=0.043647`
- baseline `biomimetic_score_delta=0.012147`
- residual `hippocampal_reactivation_headroom_change=-0.000797`
- residual `correction_survival_headroom_change=-0.006242`
- `flow_to_reply_coupling_loss_reduction=0.082128`
- `after_observed_total_tokens=195906`

Flash:

- `decision=absolute_improved_residual_partial`
- baseline `hippocampal_reactivation_delta=0.018057`
- baseline `correction_survival_proxy_delta=0.043647`
- baseline `biomimetic_score_delta=0.016831`
- residual `hippocampal_reactivation_headroom_change=-0.000797`
- residual `correction_survival_headroom_change=-0.006242`
- `flow_to_reply_coupling_loss_reduction=0.13761`
- `after_observed_total_tokens=197810`

## Stage75-Style Stability Result

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-replication-stability --progress-json artifacts\stage74\stage74_provider_progress_vs_stage72.json --progress-json artifacts\stage75\stage75_provider_progress_vs_stage72.json --progress-json artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\stage76_pro_provider_progress_vs_stage72.json --progress-json artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\stage76_flash_provider_progress_vs_stage72.json --progress-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\stage77_pro_provider_progress_vs_stage72.json --progress-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\stage77_flash_provider_progress_vs_stage72.json --output artifacts\stage77\stage77_ignition_reply_20260515\stage77_replication_stability.html
```

Result:

- `decision=replicated_replay_correction_partial_flow`
- `replicated_scope=replay_correction_only`
- `cell_count=6`
- `real_provider_cell_count=6`
- `absolute_improved_cell_count=6`
- `replay_correction_compression_cell_count=6`
- `flow_loss_reduction_cell_count=5`
- mean `hippocampal_reactivation_headroom_change=-0.000696`
- mean `correction_survival_headroom_change=-0.005373`
- mean `flow_to_reply_coupling_loss_reduction=0.075042`
- `observed_total_tokens=1176096`

## Stage76 Model-Family Result With Stage77 Cells

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-model-family-stability --model-progress deepseek-v4-pro=artifacts\stage74\stage74_provider_progress_vs_stage72.json --model-progress deepseek-v4-pro=artifacts\stage75\stage75_provider_progress_vs_stage72.json --model-progress deepseek-v4-pro=artifacts\stage76\stage76_model_family_20260515\cells\01_deepseek-v4-pro\stage76_pro_provider_progress_vs_stage72.json --model-progress deepseek-v4-flash=artifacts\stage76\stage76_model_family_20260515\cells\02_deepseek-v4-flash\stage76_flash_provider_progress_vs_stage72.json --model-progress deepseek-v4-pro=artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\stage77_pro_provider_progress_vs_stage72.json --model-progress deepseek-v4-flash=artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\stage77_flash_provider_progress_vs_stage72.json --output artifacts\stage77\stage77_ignition_reply_20260515\stage77_model_family_stability.html
```

Result:

- `decision=model_family_replay_correction_supported_flow_cell_unstable`
- `supported_scope=replay_correction_with_flow_cell_instability`
- `model_count=2`
- `cell_count=6`
- `real_provider_cell_count=6`
- `replay_correction_compression_cell_count=6`
- `flow_loss_reduction_cell_count=5`
- `flow_instability_assessment=within_model_replication_unstable_not_model_specific`
- mean `hippocampal_reactivation_headroom_change=-0.000696`
- mean `correction_survival_headroom_change=-0.005373`
- mean `flow_to_reply_coupling_loss_reduction=0.075042`
- `observed_total_tokens=1176096`

Per model:

- `deepseek-v4-pro`: `4` real cells, `4/4` replay/correction compression,
  `3/4` flow-loss reduction, mean flow reduction `0.026766`, observed tokens
  `779265`
- `deepseek-v4-flash`: `2` real cells, `2/2` replay/correction compression,
  `2/2` flow-loss reduction, mean flow reduction `0.171594`, observed tokens
  `396831`

## Interpretation

Stage77 improves the flow result, but it does not fully solve it.

The clean claim is:

```text
Explicit ignition-to-reply coupling improved real-provider flow-loss reduction
replication from 3/4 to 5/6 cells while preserving replay/correction residual
headroom compression across all 6 cells, but one prior Pro miss remains, so
flow stability is still classified as within-model/cell unstable rather than
fully solved.
```

This is publication-bounded mechanism evidence, not consciousness proof.

## Boundary

Stage77 preserves existing authority boundaries:

- provider calls happen only through the Stage60 operator-gated campaign path
- prompt changes stay inside the existing WSL subject runtime and processor fabric
- no WeChat transport
- no live runtime state
- no provider fallback
- no self-memory writes
- no policy writes
- no watcher authority
- no runtime decision authority
- no unbounded loop

## Next Gate

Stage78 should formalize the theory correspondence and falsification matrix:

- make GNW, hippocampal indexing/CLS, and predictive-processing mappings explicit
- add one more independent Pro-family replication or matched control to test
  whether the remaining flow miss is residual cell noise or a still-missing
  mechanism term
- keep claims bounded to functional coupling rather than neural consciousness

