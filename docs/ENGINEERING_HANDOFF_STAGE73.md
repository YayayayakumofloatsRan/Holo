# Engineering Handoff Stage73

Stage73 adds a biomimetic provider-progress observatory that separates absolute
DeepSeek provider improvement from residual Stage71 counterfactual headroom.

## Scope

- New module: `holo_host/biomimetic_provider_progress.py`
- New CLI command: `evaluate-biomimetic-provider-progress`
- Regression tests: `tests/test_stage73_biomimetic_provider_progress.py`
- Operator docs: `docs/STAGE73_BIOMIMETIC_PROVIDER_PROGRESS.md`

## Boundary

Stage73 is analysis-only:

- no provider call inside Stage73
- no self-memory writes
- no policy writes
- no transport writes
- no watcher authority
- no downstream MCP exposure
- no runtime decision authority
- no unbounded loop

It reads existing Stage71 JSON reports and optional Stage59/60 trace JSON. Any
new provider traffic must remain in Stage59/60.

## Runtime Contract

The command requires two Stage71 causal-ablation reports:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-provider-progress --before-json <stage71-before.json> --after-json <stage71-after.json> --output <stage73.html>
```

Optional trace JSON inputs add provider-noise fields:

```powershell
--before-trace-json <trace-before.json> --after-trace-json <trace-after.json>
```

The report writes:

- HTML
- JSON
- PNG

The report keeps:

- `absolute_progress`
- `residual_headroom`
- `provider_noise`
- `hypothesis_decision`
- bounded `publication_claims`
- authority-preserving `evidence_gate`

## DeepSeek Evidence

Completed over existing Stage71 and Stage72 real DeepSeek reports:

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
- `after_latency_outlier=true`
- `after_observed_total_tokens=135043`
- `real_provider_trace=true`
- `causal_language_bounded=true`

Interpretation:

Stage72 improved the absolute DeepSeek baseline but did not yet compress the
Stage71 replay/correction residual headroom. That makes the next experiment a
repeated or longer Stage59/60 provider campaign, not another surrogate-only
scorecard.

## Verification

Completed:

```powershell
python -m pytest tests\test_stage73_biomimetic_provider_progress.py -q
python -m pytest tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python -m py_compile holo_host\biomimetic_provider_progress.py holo_host\biomimetic_causal_ablation.py holo_host\biomimetic_consciousness_observatory.py holo_host\cli.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Results:

- focused Stage73 tests passed with `3` tests.
- related Stage70/71/73 regression passed with `10` tests.
- compile passed.
- full suite passed with `489` tests.
- public release hygiene passed.
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings.

## Next Gate

Stage74 should run a repeated or longer DeepSeek correction-reactivation provider
cell through Stage59/60, rerun Stage71, then rerun Stage73. The success criterion
should require residual headroom compression, not only absolute baseline
improvement.
