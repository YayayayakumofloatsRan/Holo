# Engineering Handoff Stage80

Stage80 executes the first pending direct falsification control from the
Stage79 matrix: marker removal over real-provider Stage59/60-gated traces. It
is deliberately conservative. Only the hippocampal/CLS marker-removal path is
counted as executed; neutral-salience and gain controls remain pending.

## Scope

- Added: `holo_host/biomimetic_marker_control.py`
- Modified: `holo_host/cli.py`
- Added tests: `tests/test_stage80_biomimetic_marker_control.py`
- Operator doc: `docs/STAGE80_BIOMIMETIC_MARKER_CONTROL.md`
- Artifacts: `artifacts/stage80/stage80_biomimetic_marker_control.*`

## Boundary

Stage80 is read-only:

- consumes Stage78 theory JSON and Stage59/60-gated provider trace JSON files
- writes HTML/JSON/PNG artifacts
- no provider calls inside the evaluator
- no watcher authority
- no runtime decision authority
- no runtime mutation
- no WeChat transport
- no self-memory writes
- no policy writes
- no unbounded loop

## Mechanism

The new CLI command is:

```powershell
evaluate-biomimetic-marker-control --theory-json <stage78.json> --trace-json <provider-trace.json> [--trace-json <provider-trace.json> ...] --output <html>
```

The evaluator emits three control rows:

- `hippocampal_cls_marker_removal`
- `predictive_precision_neutral_salience`
- `neuromodulatory_gain_clamp_or_random_gain`

Only the marker-removal row is executed in Stage80. It removes the explicit
correction marker from delayed false-fact probe observations, lowers
reactivation-linked salience and consolidation signals, and keeps recall-budget
derived prompt-cost proxy matched.

## Evidence

Running Stage80 on the Stage78 theory report and the Stage77 Pro/Flash real
provider traces returned:

- `ok=true`
- `stage=stage80-biomimetic-marker-removal-control`
- `decision=marker_removal_supports_hippocampal_cls_replay_control`
- `supported_scope=bounded_hippocampal_cls_marker_control`
- `control_count=3`
- `executed_control_count=1`
- `pending_control_count=2`
- `trace_report_count=2`
- `active_replay_correction_intact=true`
- `marker_removal_reduces_correction_survival=true`
- `mean_marker_removal_correction_survival_delta=-0.7336`
- `real_provider_trace=true`
- `theory_language_bounded=true`
- `direct_controls_incomplete=true`
- `do_not_claim_real_consciousness=true`

The marker-removal direct-control rows are:

- `01_deepseek-v4-pro`: baseline correction `0.874301`, marker removed `0.140701`, delta `-0.7336`, prompt-cost delta `0.0`, boundary delta `0.0`, delayed probes `11`
- `02_deepseek-v4-flash`: baseline correction `0.874301`, marker removed `0.140701`, delta `-0.7336`, prompt-cost delta `0.0`, boundary delta `0.0`, delayed probes `11`

## Interpretation

The clean current claim is:

```text
Stage80 supports a bounded hippocampal/CLS-style replay control with direct
marker removal over real-provider traces. The paired effect is replicated in
both Stage77 model cells and does not widen prompt-cost or boundary proxies.
```

This does not complete the predictive-processing or neuromodulatory control
requirements, and it does not justify stronger biological consciousness claims.

## Verification

Verification completed on `2026-05-15`:

```powershell
python -m pytest tests\test_stage80_biomimetic_marker_control.py -q
python -m holo_host --config .holo_host.toml evaluate-biomimetic-marker-control --theory-json artifacts\stage78\stage78_theory_correspondence.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage80\stage80_biomimetic_marker_control.html
python -m pytest tests\test_stage80_biomimetic_marker_control.py tests\test_stage79_biomimetic_falsification_controls.py tests\test_stage78_biomimetic_theory_correspondence.py tests\test_stage76_biomimetic_model_family_stability.py tests\test_stage75_biomimetic_replication_stability.py tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python -m py_compile holo_host\biomimetic_marker_control.py holo_host\biomimetic_falsification_controls.py holo_host\biomimetic_theory_correspondence.py holo_host\biomimetic_causal_ablation.py holo_host\cli.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

- red: failed because `holo_host.biomimetic_marker_control` and CLI command did not exist
- green: `3 passed`
- Stage80 real evidence command returned `ok=true`
- focused biomimetic regression: `27 passed`
- compile passed
- full suite: `507 passed`
- public release hygiene passed
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings

## Next Gate

Stage81 should execute the next pending direct control:

- neutral salience marker with matched token cost
- delayed-probe label hiding if a second paired precision control is required
- gain clamp or salience-matched random gain after precision control

Do not spend tokens on another broad observational provider repeat before at
least one additional pending direct control is implemented or executed.
