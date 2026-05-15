# Engineering Handoff Stage75

Stage75 adds a read-only replication-stability observatory over repeated
Stage73 provider-progress reports and records a second independent 42-turn
DeepSeek V4 Pro cell.

## Scope

- New module: `holo_host/biomimetic_replication_stability.py`
- New CLI command: `evaluate-biomimetic-replication-stability`
- Regression tests: `tests/test_stage75_biomimetic_replication_stability.py`
- Operator doc: `docs/STAGE75_REPLICATION_STABILITY.md`

## Boundary

Stage75 is observational/report-only:

- no provider call inside the Stage75 observatory
- Stage59 remains the only provider-call path used here
- no WeChat transport
- no live runtime state
- no provider fallback
- no self-memory writes
- no policy writes
- no watcher authority
- no runtime decision authority
- no unbounded loop

## Evidence

Independent Stage75 provider cell:

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

Stage71:

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

Stage73 against Stage72:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.json --after-json artifacts\stage75\stage75_deepseek_reactivation_replication_causal_ablation.json --before-trace-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --after-trace-json artifacts\stage75\stage75_deepseek_reactivation_replication_trace.json --output artifacts\stage75\stage75_provider_progress_vs_stage72.html
```

Result:

- `decision=absolute_improved_residual_partial`
- baseline `hippocampal_reactivation_delta=0.01339`
- baseline `correction_survival_proxy_delta=0.011948`
- residual `hippocampal_reactivation_headroom_change=-0.00013`
- residual `correction_survival_headroom_change=-0.001026`
- `flow_to_reply_coupling_loss_reduction=-0.037211`
- `after_latency_outlier=false`
- `after_observed_total_tokens=191768`

Stage75 stability:

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
- `observed_total_tokens=386618`

## Interpretation

Replay/correction compression replicated across two long DeepSeek V4 Pro cells.
Flow-coupling loss reduction did not replicate, so Stage75 is not full mechanism
support. The next experiment should test model-family stability through Stage60
repeated cells.

## Verification

Completed:

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

Stage76 should use Stage60 to run repeated DeepSeek V4 Pro and Flash cells, then
evaluate whether replay/correction compression survives model-family variation.
