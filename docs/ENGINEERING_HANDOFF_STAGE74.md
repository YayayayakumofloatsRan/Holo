# Engineering Handoff Stage74

Stage74 records the first longer real-provider headroom-compression run after
Stage73.

## Scope

- No code changes.
- New operator doc: `docs/STAGE74_LONGER_PROVIDER_HEADROOM_COMPRESSION.md`.
- Updated roadmap and handoff.
- New plan log: `docs/superpowers/plans/2026-05-15-stage74-provider-headroom-compression.md`.

## Boundary

Stage74 uses existing Stage59/71/73 paths:

- Stage59 provider trace is operator-gated and shadow-runtime isolated.
- Stage71 causal ablation is observational/counterfactual.
- Stage73 provider progress is report-only.

No new surface is allowed:

- no WeChat transport
- no live runtime state
- no provider fallback
- no self-memory writes
- no policy writes
- no watcher authority
- no runtime decision authority
- no unbounded loop

## Evidence

Provider trace:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --resume --runs 3 --turns 14 --max-total-tokens 260000 --provider-hint deepseek --model deepseek-v4-pro --lane kernel_xhigh --max-output-tokens 180 --output artifacts\stage74\stage74_deepseek_reactivation_longer_trace.html
```

Result:

- `status=complete`
- `planned_total_turns=42`
- `collected_turn_count=42`
- `real_provider_trace=true`
- `observed_total_tokens=194850`
- `stopped_reason=completed`
- `do_not_claim_real_manifold=true`
- `max_latency_ms=40408.09`

Stage71:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage74\stage74_deepseek_reactivation_longer_trace.json --output artifacts\stage74\stage74_deepseek_reactivation_longer_causal_ablation.html
```

Result:

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.010408`
- `correction_survival_proxy_delta=0.042215`
- `flow_to_reply_coupling_delta=-0.314392`
- `prompt_cost_delta=0.041666`
- `boundary_violation_delta=0.0`
- `surrogate_only=false`
- `causal_language_bounded=true`

Stage73 comparison against Stage72:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.json --after-json artifacts\stage74\stage74_deepseek_reactivation_longer_causal_ablation.json --before-trace-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --after-trace-json artifacts\stage74\stage74_deepseek_reactivation_longer_trace.json --output artifacts\stage74\stage74_provider_progress_vs_stage72.html
```

Result:

- `decision=absolute_improved_residual_partial`
- baseline `biomimetic_consciousness_score_delta=0.011601`
- baseline `hippocampal_reactivation_delta=0.017593`
- baseline `correction_survival_proxy_delta=0.043647`
- residual `hippocampal_reactivation_headroom_change=-0.000797`
- residual `correction_survival_headroom_change=-0.006242`
- `flow_to_reply_coupling_loss_reduction=0.028034`
- `after_latency_outlier=false`
- `after_observed_total_tokens=194850`
- `real_provider_trace=true`

## Interpretation

Stage74 improves the absolute DeepSeek baseline and compresses residual
counterfactual headroom relative to Stage72, but it remains partial support. The
next gate should test replication stability across independent cells.

## Verification

Completed:

```powershell
python -m pytest tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Results:

- related Stage70/71/73 regression passed with `10` tests.
- public release hygiene passed.
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings.

## Next Gate

Stage75 should run a second independent long DeepSeek trace or a Stage60
multi-cell campaign, then require headroom compression across repeated cells.
