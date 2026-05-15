# Engineering Handoff Stage78

Stage78 adds a read-only theory-correspondence observatory over the Stage77
model-family evidence. It is the first stage whose primary output is a
publication-bounded neuroscience mapping rather than another broad provider
repeat.

## Scope

- Added: `holo_host/biomimetic_theory_correspondence.py`
- Modified: `holo_host/cli.py`
- Added tests: `tests/test_stage78_biomimetic_theory_correspondence.py`
- Operator doc: `docs/STAGE78_BIOMIMETIC_THEORY_CORRESPONDENCE.md`

## Boundary

Stage78 is read-only:

- consumes Stage77/Stage76 model-family stability JSON
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
python -m holo_host --config .holo_host.toml evaluate-biomimetic-theory-correspondence --model-family-json artifacts\stage77\stage77_ignition_reply_20260515\stage77_model_family_stability.json --output artifacts\stage78\stage78_theory_correspondence.html
```

The evaluator builds four rows:

- `global_neuronal_workspace`
- `hippocampal_indexing_cls`
- `predictive_processing_precision`
- `neuromodulatory_gain`

Every row must include Holo variables, measurable predictions,
disconfirming controls, support status, and a bounded evidence summary.

## Evidence

Running the Stage78 command on the Stage77 model-family report returned:

- `ok=true`
- `stage=stage78-biomimetic-theory-correspondence`
- `decision=publishable_bounded_replay_correction_with_partial_flow`
- `supported_scope=replay_correction_with_partial_gnw_flow`
- `theory_count=4`
- `falsifiable_theory_count=4`
- `supported_theory_count=2`
- `partial_theory_count=1`
- `needs_control_theory_count=1`
- `publication_readiness=bounded_preprint_candidate`
- `source_cell_count=6`
- `source_observed_total_tokens=1176096`
- `real_provider_trace=true`
- `theory_language_bounded=true`
- `do_not_claim_real_consciousness=true`

## Interpretation

The clean current claim is:

```text
Stage78 supports a bounded replay/correction result with explicit
hippocampal-indexing/CLS and predictive-processing correspondence, while GNW
ignition-to-reply coupling remains partial because flow improves in 5/6 cells
but remains within-model/cell unstable.
```

Neuromodulatory gain is now mapped to concrete variables and falsification
controls, but it is not yet a supported claim. It needs a gain-clamp or
random-gain control.

## Verification

Verification completed on `2026-05-15`:

```powershell
python -m pytest tests\test_stage78_biomimetic_theory_correspondence.py -q
python -m pytest tests\test_stage78_biomimetic_theory_correspondence.py tests\test_stage76_biomimetic_model_family_stability.py tests\test_stage75_biomimetic_replication_stability.py tests\test_stage73_biomimetic_provider_progress.py tests\test_stage71_biomimetic_causal_ablation.py tests\test_stage70_biomimetic_consciousness_observatory.py -q
python -m py_compile holo_host\biomimetic_theory_correspondence.py holo_host\biomimetic_model_family_stability.py holo_host\cli.py
python -m pytest -q
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

- red: failed because `holo_host.biomimetic_theory_correspondence` and CLI command did not exist
- green: `3 passed`
- focused biomimetic regression: `21 passed`
- compile passed
- full suite: `501 passed`
- public release hygiene passed
- `git diff --check` had no whitespace errors; Git printed only CRLF warnings

## Next Gate

Run targeted falsification controls before spending on another broad
observational repeat:

- prompt-cost-matched ignition-null control
- correction-label shuffle or marker-removal control
- neutral salience marker control
- gain-clamp or salience-matched random-gain control

The next gate should preserve replay/correction compression and narrow the
remaining GNW flow-coupling instability beyond generic provider-cell noise.
