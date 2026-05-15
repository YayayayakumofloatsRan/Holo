# Stage74 Longer Provider Headroom Compression

## What Stage74 Adds

Stage74 runs a longer real DeepSeek correction-reactivation provider trace through
the existing Stage59 path, then evaluates the result with the existing Stage71
and Stage73 analysis chain.

No new runtime authority is added. Stage74 is a provider-evidence milestone:

- Stage59 collects a longer real-provider trace in shadow runtime.
- Stage71 estimates residual replay/correction counterfactual headroom.
- Stage73 compares Stage72 against Stage74 to separate absolute baseline gains
  from headroom compression.

## Run

Provider trace:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --resume --runs 3 --turns 14 --max-total-tokens 260000 --provider-hint deepseek --model deepseek-v4-pro --lane kernel_xhigh --max-output-tokens 180 --output artifacts\stage74\stage74_deepseek_reactivation_longer_trace.html
```

Stage71 evaluation:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-causal-ablation --lab-json artifacts\stage74\stage74_deepseek_reactivation_longer_trace.json --output artifacts\stage74\stage74_deepseek_reactivation_longer_causal_ablation.html
```

Stage73 comparison against Stage72:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.json --after-json artifacts\stage74\stage74_deepseek_reactivation_longer_causal_ablation.json --before-trace-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --after-trace-json artifacts\stage74\stage74_deepseek_reactivation_longer_trace.json --output artifacts\stage74\stage74_provider_progress_vs_stage72.html
```

## Provider Trace Result

- `status=complete`
- `planned_total_turns=42`
- `collected_turn_count=42`
- `real_provider_trace=true`
- `observed_total_tokens=194850`
- `stopped_reason=completed`
- `do_not_claim_real_manifold=true`
- `max_latency_ms=40408.09`

The longer trace removed the Stage72 extreme latency outlier:

| metric | Stage72 | Stage74 |
| --- | ---: | ---: |
| collected turns | `30` | `42` |
| observed total tokens | `135043` | `194850` |
| max latency ms | `617411.46` | `40408.09` |
| latency outlier >= 60000 ms | `true` | `false` |

## Stage71 Result

- `decision=partial_support_real_provider`
- `hippocampal_reactivation_delta=0.010408`
- `correction_survival_proxy_delta=0.042215`
- `flow_to_reply_coupling_delta=-0.314392`
- `prompt_cost_delta=0.041666`
- `boundary_violation_delta=0.0`
- `surrogate_only=false`
- `causal_language_bounded=true`
- `do_not_claim_real_consciousness=true`

Stage74 does not yet convert the Stage71 decision to full support. It does,
however, reduce both measured replay/correction residual headroom values.

## Stage73 Comparison Against Stage72

- `decision=absolute_improved_residual_partial`
- `provider_interpretation=provider_improved_but_counterfactual_headroom_remains`
- baseline `biomimetic_consciousness_score_delta=0.011601`
- baseline `hippocampal_reactivation_delta=0.017593`
- baseline `correction_survival_proxy_delta=0.043647`
- residual `hippocampal_reactivation_headroom_change=-0.000797`
- residual `correction_survival_headroom_change=-0.006242`
- `flow_to_reply_coupling_loss_reduction=0.028034`
- `after_observed_total_tokens=194850`
- `after_latency_outlier=false`
- `real_provider_trace=true`

Interpretation:

Stage74 is the first real-provider evidence that longer correction-reactivation
cells can both improve the observed baseline and compress residual
counterfactual headroom. The effect is still partial: the residual headroom is
present, so this is not a complete mechanism solve.

## Boundary

Stage74 keeps the Stage59/71/73 authority boundaries:

- no WeChat transport
- no live runtime state use
- no provider fallback
- no self-memory writes
- no policy writes
- no watcher authority
- no runtime decision authority
- no unbounded loop

Provider calls remain operator-gated and shadow-runtime isolated through Stage59.

## Next Gate

Stage75 should test replication stability, not just trace length. The immediate
target is either:

- a second independent 42-turn DeepSeek V4 Pro trace, or
- a Stage60 campaign with repeated `deepseek-v4-pro` and `deepseek-v4-flash`
  cells, followed by Stage71/73 comparison.

Acceptance should require residual headroom compression across repeated cells,
not one successful longer trace.
