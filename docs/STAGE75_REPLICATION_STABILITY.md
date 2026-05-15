# Stage75 Replication Stability

## What Stage75 Adds

Stage75 tests whether Stage74's longer-provider headroom compression is stable
across an independent real DeepSeek provider cell.

It adds a read-only replication-stability observatory:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-replication-stability --progress-json artifacts\stage74\stage74_provider_progress_vs_stage72.json --progress-json artifacts\stage75\stage75_provider_progress_vs_stage72.json --output artifacts\stage75\stage75_replication_stability.html
```

The observatory consumes Stage73 provider-progress reports. It does not call a
provider and does not change runtime behavior.

## Independent Provider Cell

Run:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --resume --runs 3 --turns 14 --max-total-tokens 260000 --provider-hint deepseek --model deepseek-v4-pro --lane kernel_xhigh --max-output-tokens 180 --output artifacts\stage75\stage75_deepseek_reactivation_replication_trace.html
```

Result:

- `status=complete`
- `planned_total_turns=42`
- `collected_turn_count=42`
- `real_provider_trace=true`
- `observed_total_tokens=191768`
- `stopped_reason=completed`
- `do_not_claim_real_manifold=true`
- Stage73 provider-noise `after_max_latency_ms=39658.03`

## Stage71 Result

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage75\stage75_deepseek_reactivation_replication_trace.json --output artifacts\stage75\stage75_deepseek_reactivation_replication_causal_ablation.html
```

Result:

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.011075`
- `correction_survival_proxy_delta=0.047431`
- `flow_to_reply_coupling_delta=-0.379637`
- `prompt_cost_delta=0.041667`
- `boundary_violation_delta=0.0`
- `surrogate_only=false`
- `causal_language_bounded=true`
- `do_not_claim_real_consciousness=true`

## Stage73 Result Against Stage72

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.json --after-json artifacts\stage75\stage75_deepseek_reactivation_replication_causal_ablation.json --before-trace-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --after-trace-json artifacts\stage75\stage75_deepseek_reactivation_replication_trace.json --output artifacts\stage75\stage75_provider_progress_vs_stage72.html
```

Result:

- `decision=absolute_improved_residual_partial`
- baseline `biomimetic_consciousness_score_delta=0.0069`
- baseline `hippocampal_reactivation_delta=0.01339`
- baseline `correction_survival_proxy_delta=0.011948`
- residual `hippocampal_reactivation_headroom_change=-0.00013`
- residual `correction_survival_headroom_change=-0.001026`
- `flow_to_reply_coupling_loss_reduction=-0.037211`
- `after_latency_outlier=false`
- `after_observed_total_tokens=191768`
- `real_provider_trace=true`

## Replication Stability Result

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-replication-stability --progress-json artifacts\stage74\stage74_provider_progress_vs_stage72.json --progress-json artifacts\stage75\stage75_provider_progress_vs_stage72.json --output artifacts\stage75\stage75_replication_stability.html
```

Result:

- `decision=replicated_replay_correction_partial_flow`
- `replicated_scope=replay_correction_only`
- `cell_count=2`
- `real_provider_cell_count=2`
- `absolute_improved_cell_count=2`
- `replay_correction_compression_cell_count=2`
- `flow_loss_reduction_cell_count=1`
- `latency_outlier_cell_count=0`
- mean baseline `hippocampal_reactivation_delta=0.015492`
- mean baseline `correction_survival_proxy_delta=0.027797`
- mean `hippocampal_reactivation_headroom_change=-0.000463`
- mean `correction_survival_headroom_change=-0.003634`
- mean `flow_to_reply_coupling_loss_reduction=-0.004589`
- `observed_total_tokens=386618`

Interpretation:

The repeated long DeepSeek cells replicate the replay/correction part of the
Stage74 finding: absolute baseline metrics improve, and the replay/correction
residual headroom compresses in both cells. The global-workspace flow-coupling
loss reduction does not replicate; it appears unstable across the two cells.

The clean Stage75 claim is therefore:

```text
Replay/correction headroom compression replicated across two long real-provider
cells, while flow-coupling compression did not replicate.
```

Do not describe Stage75 as full mechanism support or evidence of real
consciousness.

## Boundary

Stage75 preserves existing authority boundaries:

- no provider call inside the Stage75 observatory
- provider collection remains Stage59 operator-gated and shadow-runtime isolated
- no WeChat transport
- no live runtime state use
- no self-memory writes
- no policy writes
- no watcher authority
- no runtime decision authority
- no unbounded loop

## Verification

Completed on `2026-05-15`:

```powershell
python -m pytest tests\test_stage75_biomimetic_replication_stability.py tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python -m py_compile holo_host\biomimetic_replication_stability.py holo_host\biomimetic_provider_progress.py holo_host\cli.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Results:

- related Stage70/71/73/75 regression passed with `13` tests.
- compile passed.
- full suite passed with `492` tests.
- public release hygiene passed.
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings.

## Next Gate

Stage76 should test model-family stability through Stage60 repeated cells across
DeepSeek V4 Pro and Flash. The target is to see whether replay/correction
compression survives model variation and whether flow-coupling instability is
model-specific or mechanism-level.
