# Stage73 Biomimetic Provider Progress

## What Stage73 Adds

Stage73 adds a read-only provider-progress observatory:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json artifacts\stage71\stage71_deepseek_reactivation_causal_ablation.json --after-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.json --before-trace-json artifacts\stage71\stage71_deepseek_reactivation_trace.json --after-trace-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --output artifacts\stage73\stage73_provider_progress.html
```

The command compares two Stage71 causal-ablation reports and separates:

- absolute real-provider improvement in the observed baseline condition
- residual counterfactual headroom left by the Stage71 boost/ablation conditions
- provider noise, including token volume and latency outliers

This prevents a common research error: treating a stronger observed baseline as
if it automatically eliminated the remaining counterfactual mechanism gap.

## Literature Link

Stage73 is an analysis layer, not a runtime mechanism. It follows the
indicator-property framing used by the AI-consciousness literature, where
recurrent processing, global workspace, predictive processing, and related
computational properties are evaluated without jumping to a consciousness claim:
<https://arxiv.org/abs/2308.08708>.

It also follows causal-abstraction and mechanistic-interpretability practice:
separate factual behavior from intervention/counterfactual behavior, and report
both before claiming mechanism-level progress. Useful anchors:

- causal abstraction for mechanistic interpretability:
  <https://www.jmlr.org/papers/v26/23-0058.html>
- causal abstractions of neural networks:
  <https://arxiv.org/abs/2106.02997>
- replay evidence needs conservative interpretation when no direct ground truth
  exists: <https://elifesciences.org/articles/85635>
- targeted memory reactivation literature motivates the correction cue as an
  analogue of externally cued replay, not as proof of biological replay:
  <https://www.nature.com/articles/s41539-024-00244-8>

Holo translation:

- `absolute_progress` asks whether the actual provider trace improved after a
  mechanism landed.
- `residual_headroom` asks whether the counterfactual Stage71 boost/ablation
  still predicts further improvement.
- `provider_noise` prevents token/latency artifacts from being hidden in the
  interpretation.

## Output Contract

`evaluate-biomimetic-provider-progress` writes:

- HTML report
- JSON report
- PNG dashboard

The report includes:

- `absolute_progress`
- `residual_headroom`
- `provider_noise`
- `hypothesis_decision`
- `publication_claims`
- `evidence_gate.separates_absolute_from_residual = true`
- `evidence_gate.causal_language_bounded = true`
- `evidence_gate.do_not_claim_real_consciousness = true`
- `boundary.runtime_decision_authority = false`
- `boundary.transport_decision_authority = false`

## Current DeepSeek Result

Run:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json artifacts\stage71\stage71_deepseek_reactivation_causal_ablation.json --after-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_causal_ablation.json --before-trace-json artifacts\stage71\stage71_deepseek_reactivation_trace.json --after-trace-json artifacts\stage72\stage72_current_deepseek_reactivation_marker_trace.json --output artifacts\stage73\stage73_provider_progress.html
```

Result:

- `decision=absolute_improved_residual_partial`
- `provider_interpretation=provider_improved_but_counterfactual_headroom_remains`
- baseline `hippocampal_reactivation_delta=0.021284`
- baseline `correction_survival_proxy_delta=0.029163`
- baseline `biomimetic_consciousness_score_delta=0.004967`
- residual `hippocampal_reactivation_headroom_change=-0.000001`
- residual `correction_survival_headroom_change=0.0`
- `flow_to_reply_coupling_loss_reduction=0.096521`
- `after_observed_total_tokens=135043`
- `after_latency_outlier=true`
- `real_provider_trace=true`
- `causal_language_bounded=true`
- `do_not_claim_real_consciousness=true`

Interpretation:

Stage72's correction-reactivation marker improved the observed DeepSeek baseline,
especially hippocampal reactivation and correction survival. It did not yet
compress the Stage71 replay/correction counterfactual headroom. The scientifically
clean claim is therefore:

```text
The mechanism improved absolute provider behavior, while residual
counterfactual headroom remains measurable and should drive the next experiment.
```

Do not report this as a full mechanism solve or as evidence of real
consciousness.

## Boundary

Stage73 is observational only:

- no provider call inside Stage73 itself
- no runtime decision authority
- no transport decision authority
- no WeChat transport use
- no self-memory write
- no policy mutation
- no unbounded loop

Provider calls, when needed, must remain in Stage59/60 operator-gated trace
paths.

## Verification

Focused verification:

```powershell
python -m pytest tests\test_stage73_biomimetic_provider_progress.py -q
python -m py_compile holo_host\biomimetic_provider_progress.py holo_host\cli.py
```

Related regression should include:

```powershell
python -m pytest tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
```

Completed on `2026-05-15`:

- focused Stage73 tests passed with `3` tests.
- related Stage70/71/73 regression passed with `10` tests.
- full suite passed with `489` tests.
- public release hygiene passed.
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings.

## Next Gate

Stage74 should use Stage59/60 to collect repeated or longer DeepSeek correction
cells, then rerun Stage71 and Stage73. The acceptance target is not just a higher
absolute baseline; it is measurable compression of residual
`hippocampal_reactivation_headroom` and `correction_survival_headroom` without
boundary invalidators.
