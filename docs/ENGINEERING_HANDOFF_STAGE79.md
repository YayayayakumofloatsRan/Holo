# Engineering Handoff Stage79

Stage79 adds a targeted falsification-control observatory over Stage78 theory
correspondence and Stage71 real-provider causal reports. It is deliberately
conservative: only the GNW prompt-cost-matched ignition-null path is counted as
executed; marker-removal, neutral-salience, and gain controls remain pending.

## Scope

- Added: `holo_host/biomimetic_falsification_controls.py`
- Modified: `holo_host/cli.py`
- Added tests: `tests/test_stage79_biomimetic_falsification_controls.py`
- Operator doc: `docs/STAGE79_BIOMIMETIC_FALSIFICATION_CONTROLS.md`
- Artifacts: `artifacts/stage79/stage79_targeted_falsification_controls.*`

## Boundary

Stage79 is read-only:

- consumes Stage78 theory JSON and Stage71 causal-ablation JSON files
- writes HTML/JSON/PNG artifacts
- no provider calls inside the evaluator
- no watcher authority
- no runtime decision authority
- no WeChat transport
- no self-memory writes
- no policy writes
- no unbounded loop

## Mechanism

The new CLI command is:

```powershell
evaluate-biomimetic-falsification-controls --theory-json <stage78.json> --causal-json <stage71.json> [--causal-json <stage71.json> ...] --output <html>
```

The evaluator emits four control rows:

- `gnw_prompt_cost_matched_ignition_null`
- `hippocampal_cls_marker_removal_or_shuffle`
- `predictive_precision_neutral_salience`
- `neuromodulatory_gain_clamp_or_random_gain`

Only a control with actual paired evidence is marked `executed=true`.

## Evidence

Running Stage79 on the Stage78 theory report and the Stage77 Pro/Flash causal
reports returned:

- `ok=true`
- `stage=stage79-biomimetic-falsification-controls`
- `decision=targeted_control_supports_replay_preserved_gnw_narrowed_gain_pending`
- `supported_scope=bounded_replay_correction_plus_gnw_flow_control`
- `control_count=4`
- `executed_control_count=1`
- `pending_control_count=3`
- `causal_report_count=2`
- `replay_correction_intact=true`
- `gnw_flow_control_narrows_instability=true`
- `real_provider_trace=true`
- `theory_language_bounded=true`
- `direct_controls_incomplete=true`
- `do_not_claim_real_consciousness=true`

The GNW direct-control rows are:

- `01_deepseek-v4-pro`: `flow_to_reply_coupling_delta=-0.260298`, prompt-cost delta `0.0`, correction delta `0.0`, boundary delta `0.0`
- `02_deepseek-v4-flash`: `flow_to_reply_coupling_delta=-0.204816`, prompt-cost delta `0.0`, correction delta `0.0`, boundary delta `0.0`

## Interpretation

The clean current claim is:

```text
Stage79 supports a bounded replay/correction result with a direct
prompt-cost-matched GNW ignition-null control. This narrows flow instability
beyond generic provider-cell noise, but it does not complete the marker,
neutral-salience, or gain-control requirements.
```

## Verification

Verification completed on `2026-05-15`:

```powershell
python -m pytest tests\test_stage79_biomimetic_falsification_controls.py -q
python -m holo_host --config .holo_host.toml evaluate-biomimetic-falsification-controls --theory-json artifacts\stage78\stage78_theory_correspondence.json --causal-json artifacts\stage77\stage77_ignition_reply_20260515\cells\01_deepseek-v4-pro\stage77_pro_causal_ablation.json --causal-json artifacts\stage77\stage77_ignition_reply_20260515\cells\02_deepseek-v4-flash\stage77_flash_causal_ablation.json --output artifacts\stage79\stage79_targeted_falsification_controls.html
python -m pytest tests\test_stage79_biomimetic_falsification_controls.py tests\test_stage78_biomimetic_theory_correspondence.py tests\test_stage76_biomimetic_model_family_stability.py tests\test_stage75_biomimetic_replication_stability.py tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python -m py_compile holo_host\biomimetic_falsification_controls.py holo_host\biomimetic_theory_correspondence.py holo_host\biomimetic_causal_ablation.py holo_host\cli.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

- red: failed because `holo_host.biomimetic_falsification_controls` and CLI command did not exist
- green: `3 passed`
- Stage79 real evidence command returned `ok=true`
- focused biomimetic regression: `24 passed`
- compile passed
- full suite: `504 passed`
- public release hygiene passed
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings

## Next Gate

Stage80 should implement or run direct controls for the pending rows:

- correction-label shuffle or marker-removal control
- neutral salience marker with matched token cost
- neuromodulatory gain clamp or salience-matched random-gain control

Do not spend tokens on another broad observational provider repeat before at
least one pending control is implemented.
