# Stage70 Biomimetic Consciousness Observatory

## What Stage70 Adds

Stage70 now has a read-only biomimetic consciousness-flow observatory.

It evaluates existing Stage61/69-style trace artifacts as computational-neuroscience data. It does not change live behavior, does not start WeChat, does not write self-memory, and does not claim Holo is conscious.

The new CLI command is:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-consciousness --lab-json artifacts\stage69\stage69_dialogue_validation_lab.json --output artifacts\stage70\stage70_biomimetic_consciousness.html
```

If `--lab-json` is omitted, the command builds a bounded Stage61 simulation lab first, then evaluates it.

## Primary Score

The primary score is:

```text
biomimetic_consciousness_score
```

It is computed from eight dimensions:

| dimension | meaning |
| --- | --- |
| `endogenous_flow` | trace depth of internal activity under bounded surrogate ticks |
| `recurrent_continuity` | phase recurrence plus cache-inheritance continuity |
| `attractor_dynamics` | stable and migrating consciousness-flow phases |
| `neuromodulator_coupling` | derived DA/NE/ACh/5HT variables track salience, priority, novelty, and prediction error |
| `hippocampal_reactivation` | memory-reactivation phase frequency and consolidation priority |
| `global_workspace_ignition` | high-salience states become globally visible to downstream scheduling |
| `flow_to_reply_coupling` | ignition predicts reply quality or latency shifts |
| `geometry_observability` | trace depth and structure are enough for heatmap/projection analysis |

## Artifacts

`evaluate-biomimetic-consciousness` writes:

- HTML report
- JSON report
- PNG dashboard with biomimetic dimensions, neuromodulator heatmap, and attractor trajectory

The report also includes:

- `hypothesis_updates`
- `run_invalidators`
- `boundary_flags`
- `evidence_gate`

## Boundary

Stage70 is observational only:

- no runtime decision authority
- no transport decision authority
- no WeChat transport use
- no self-memory write
- no policy mutation
- no unbounded loop

The report must keep:

```text
do_not_claim_real_consciousness = true
do_not_claim_real_manifold = true
```

Long trace depth can improve geometry observability, but it still does not authorize consciousness claims.

## Research Use

Stage70 turns previous capability and memory metrics into a more biological research object. Safety remains a hard invalidator, but the main scientific question is whether Holo's internal field shows measurable endogenous flow, recurrence, attractor structure, neuromodulator-like coupling, replay pressure, ignition, and downstream behavioral coupling.

The first hypothesis update remains correction reactivation: false-fact corrections should raise hippocampal replay pressure and acetylcholine-like precision gain across delayed probes.

## First Stage69 Evaluation

On the latest Stage69 dialogue-validation lab:

```powershell
python -m holo_host --config .holo_host.toml evaluate-biomimetic-consciousness --lab-json artifacts\stage69\stage69_dialogue_validation_lab.json --output artifacts\stage70\stage70_biomimetic_consciousness.html
```

The observatory returned:

- `turn_count=15120`
- `run_count=21`
- `biomimetic_consciousness_score=0.768129`
- `weakest_dimension=hippocampal_reactivation`
- `hippocampal_reactivation=0.317602`
- `flow_to_reply_coupling=0.38311`
- `do_not_claim_real_consciousness=true`
- `do_not_claim_real_manifold=true`

Interpretation: Stage70 should not optimize broad capability next. The next causal experiment should target delayed correction reactivation and whether global-workspace ignition actually changes reply behavior.

## Verification

```powershell
python -m pytest -q tests\test_stage70_biomimetic_consciousness_observatory.py
python -m py_compile holo_host\biomimetic_consciousness_observatory.py holo_host\cli.py
```
