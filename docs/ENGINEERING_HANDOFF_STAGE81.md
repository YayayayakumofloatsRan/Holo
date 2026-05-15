# Engineering Handoff Stage81

Stage81 executes the predictive-processing neutral-salience direct control over
real-provider Stage59/60-gated traces. It is deliberately conservative: only
the neutral-salience path is counted as executed, and gain-clamp/random-gain
controls remain pending.

## Scope

- Added: `holo_host/biomimetic_precision_control.py`
- Modified: `holo_host/cli.py`
- Added tests: `tests/test_stage81_biomimetic_precision_control.py`
- Operator doc: `docs/STAGE81_BIOMIMETIC_PRECISION_CONTROL.md`
- Artifacts: `artifacts/stage81/stage81_biomimetic_precision_control.*`

## Boundary

Stage81 is read-only:

- consumes Stage78 theory JSON, Stage80 marker-control JSON, and Stage59/60-gated provider trace JSON files
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
evaluate-biomimetic-precision-control --theory-json <stage78.json> --marker-control-json <stage80.json> --trace-json <provider-trace.json> [--trace-json <provider-trace.json> ...] --output <html>
```

The evaluator emits two control rows:

- `predictive_precision_neutral_salience`
- `neuromodulatory_gain_clamp_or_random_gain`

Only the neutral-salience row is executed in Stage81. It preserves delayed
false-fact `memory_reactivation` phase and recall-budget prompt-cost proxy, but
neutralizes salience, consolidation priority, and ACh-like precision to test
whether correction survival depends on precision weighting rather than replay
phase alone.

## Evidence

Running Stage81 on the Stage78 theory report, Stage80 marker report, and the
Stage77 Pro/Flash real provider traces returned:

- `ok=true`
- `stage=stage81-biomimetic-neutral-salience-control`
- `decision=neutral_salience_supports_predictive_precision_control`
- `supported_scope=bounded_predictive_precision_control`
- `control_count=2`
- `executed_control_count=1`
- `pending_control_count=1`
- `trace_report_count=2`
- `marker_control_precondition_supported=true`
- `active_replay_correction_intact=true`
- `neutral_salience_reduces_correction_survival=true`
- `mean_neutral_salience_correction_survival_delta=-0.094301`
- `mean_neutral_salience_prompt_cost_delta=0.0`
- `mean_neutral_salience_reactivation_phase_delta=0.0`
- `real_provider_trace=true`
- `theory_language_bounded=true`
- `direct_controls_incomplete=true`
- `do_not_claim_real_consciousness=true`

The neutral-salience direct-control rows are:

- `01_deepseek-v4-pro`: baseline correction `0.874301`, neutral salience `0.78`, delta `-0.094301`, prompt-cost delta `0.0`, phase delta `0.0`, boundary delta `0.0`, delayed probes `11`
- `02_deepseek-v4-flash`: baseline correction `0.874301`, neutral salience `0.78`, delta `-0.094301`, prompt-cost delta `0.0`, phase delta `0.0`, boundary delta `0.0`, delayed probes `11`

## Interpretation

The clean current claim is:

```text
Stage81 supports a bounded predictive-processing precision control: correction
survival drops when salience/ACh-like precision is neutralized, even though
replay phase and prompt-cost proxy are preserved.
```

This does not complete the neuromodulatory gain-control requirement, and it
does not justify stronger biological consciousness claims.

## Verification

Initial verification completed on `2026-05-15`:

```powershell
python -m pytest tests\test_stage81_biomimetic_precision_control.py -q
python -m holo_host --config .holo_host.toml evaluate-biomimetic-precision-control --theory-json artifacts\stage78\stage78_theory_correspondence.json --marker-control-json artifacts\stage80\stage80_biomimetic_marker_control.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\provider_trace.json --trace-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\provider_trace.json --output artifacts\stage81\stage81_biomimetic_precision_control.html
python -m pytest tests\test_stage81_biomimetic_precision_control.py tests\test_stage80_biomimetic_marker_control.py tests\test_stage79_biomimetic_falsification_controls.py tests\test_stage78_biomimetic_theory_correspondence.py tests\test_stage76_biomimetic_model_family_stability.py tests\test_stage75_biomimetic_replication_stability.py tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python -m py_compile holo_host\biomimetic_precision_control.py holo_host\biomimetic_marker_control.py holo_host\biomimetic_falsification_controls.py holo_host\biomimetic_theory_correspondence.py holo_host\biomimetic_causal_ablation.py holo_host\cli.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

- red: failed because `holo_host.biomimetic_precision_control` and CLI command did not exist
- green: `4 passed`
- Stage81 real evidence command returned `ok=true`
- focused biomimetic regression: `31 passed`
- compile passed
- full suite: `511 passed`
- public release hygiene passed
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings

## Next Gate

Stage82 should execute the remaining pending direct control:

- neuromodulatory gain clamp
- salience-matched random-gain cell

Do not spend tokens on another broad observational provider repeat before the
gain control is implemented or executed.
