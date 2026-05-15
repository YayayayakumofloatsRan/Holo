# Stage81 Biomimetic Precision Control Design

## Goal

Stage81 executes the predictive-processing neutral-salience control after
Stage80. It must test whether correction survival remains strong when salience
and ACh-like precision are neutralized while replay phase and prompt-cost proxy
are preserved.

## Boundaries

- WSL remains the only brain and only decision authority.
- Windows remains transport and tooling only.
- No watcher/runtime decision authority.
- No WeChat transport changes.
- No self-memory writes.
- No policy writes.
- No new unbounded loop.
- No provider calls inside the Stage81 evaluator.

## Design

Add `holo_host/biomimetic_precision_control.py`. It consumes:

- Stage78 theory-correspondence JSON
- Stage80 marker-control JSON
- one or more Stage59/60-gated real-provider trace JSON reports

It emits:

- `control_results`
- `control_summary`
- `hypothesis_decision`
- `publication_claims`
- HTML/JSON/PNG artifacts

The evaluator should keep delayed false-fact probes in `memory_reactivation`
phase and keep recall budget unchanged. It should neutralize salience,
consolidation priority, and ACh-like precision. The control passes only when
correction survival drops, replay/correction is intact before neutralization,
the Stage80 marker-control precondition is supported, prompt cost stays
matched, phase delta stays zero, and boundary deltas stay zero across all
supplied real-provider cells.

## Acceptance

- New tests fail before implementation and pass after implementation.
- CLI writes HTML/JSON/PNG artifacts.
- Neutral-salience control is marked `supported_direct_control` only when all
  supplied cells pass correction-loss, prompt-cost, phase-preservation, and
  boundary checks.
- Stage80 marker-control precondition remains supported.
- Neuromodulatory gain controls remain visibly pending.
- Evidence gates keep `do_not_claim_real_consciousness=true` and bounded theory
  language.
