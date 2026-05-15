# Engineering Handoff Stage76

Stage76 adds a read-only model-family stability observatory over model-labeled
Stage73 provider-progress reports and records a repeated Stage60 campaign across
DeepSeek V4 Pro and Flash.

## Scope

- New module: `holo_host/biomimetic_model_family_stability.py`
- New CLI command: `evaluate-biomimetic-model-family-stability`
- Regression tests: `tests/test_stage76_biomimetic_model_family_stability.py`
- Operator doc: `docs/STAGE76_MODEL_FAMILY_STABILITY.md`

## Boundary

Stage76 is observational/report-only after provider collection:

- real provider collection uses the existing Stage60 operator-gated campaign path
- each Stage60 executed cell uses shadow runtime state by default
- no provider call inside the Stage76 observatory
- no WeChat transport
- no live runtime state
- no provider fallback
- no self-memory writes
- no policy writes
- no watcher authority
- no runtime decision authority
- no unbounded loop

## Evidence

Stage60 model-family campaign:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --execute --campaign-id stage76_model_family_20260515 --models deepseek-v4-pro,deepseek-v4-flash --runs-per-model 3 --turns 14 --max-total-tokens-per-cell 260000 --provider-hint deepseek --lane auto --max-output-tokens 180 --output-root artifacts\stage76\stage76_model_family_20260515
```

Result:

- `status=complete`
- `planned_total_turns=84`
- `real_provider_cell_count=2`
- `collected_turn_count=84`
- `observed_total_tokens=395762`
- `top_model=deepseek-v4-flash`
- `top_score=0.9019`
- `do_not_claim_major_breakthrough=true`

Stage71:

- Pro: `decision=partial_support_real_provider`,
  `hippocampal_reactivation_delta=0.010344`,
  `correction_survival_proxy_delta=0.042215`,
  `flow_to_reply_coupling_delta=-0.308315`,
  `boundary_violation_delta=0.0`
- Flash: `decision=partial_support_real_provider`,
  `hippocampal_reactivation_delta=0.010408`,
  `correction_survival_proxy_delta=0.042215`,
  `flow_to_reply_coupling_delta=-0.136848`,
  `boundary_violation_delta=0.0`

Stage73 against Stage72:

- Pro: `decision=absolute_improved_residual_partial`,
  `baseline_hippocampal_reactivation_delta=0.018121`,
  `baseline_correction_survival_proxy_delta=0.043647`,
  `hippocampal_reactivation_headroom_change=-0.000861`,
  `correction_survival_headroom_change=-0.006242`,
  `flow_to_reply_coupling_loss_reduction=0.034111`,
  `after_observed_total_tokens=196741`
- Flash: `decision=absolute_improved_residual_partial`,
  `baseline_hippocampal_reactivation_delta=0.018057`,
  `baseline_correction_survival_proxy_delta=0.043647`,
  `hippocampal_reactivation_headroom_change=-0.000797`,
  `correction_survival_headroom_change=-0.006242`,
  `flow_to_reply_coupling_loss_reduction=0.205578`,
  `after_observed_total_tokens=199021`

Stage75-style stability over Stage74, Stage75, Stage76-Pro, and Stage76-Flash:

- `decision=replicated_replay_correction_partial_flow`
- `cell_count=4`
- `real_provider_cell_count=4`
- `absolute_improved_cell_count=4`
- `replay_correction_compression_cell_count=4`
- `flow_loss_reduction_cell_count=3`
- `observed_total_tokens=782380`

Stage76 model-family stability:

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
- `observed_total_tokens=782380`

## Interpretation

Replay/correction residual headroom compression survived both repeated cells
and DeepSeek model-family variation. Flow-coupling compression did not survive
all repeated cells, but it is not a clean model-family split: Pro reduced flow
loss in two of three Pro cells, Flash reduced it in its cell, and the only miss
was one independent Pro cell from Stage75. The current state is therefore
within-model/cell instability rather than model-specific instability or
mechanism-level impossibility.

## Verification

Completed:

```powershell
python -m pytest tests\test_stage76_biomimetic_model_family_stability.py tests\test_stage75_biomimetic_replication_stability.py tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python -m py_compile holo_host\biomimetic_model_family_stability.py holo_host\biomimetic_replication_stability.py holo_host\biomimetic_provider_progress.py holo_host\cli.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Results:

- related Stage70/71/73/75/76 regression passed with `16` tests.
- compile passed.
- full suite passed with `495` tests.
- public release hygiene passed.
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings.

## Next Gate

Stage77 should implement a mechanism-level flow-coupling intervention rather
than only collecting more traces. The target should be explicit
global-workspace ignition-to-reply coupling that can be evaluated through the
same Stage71/73/76 evidence chain.
