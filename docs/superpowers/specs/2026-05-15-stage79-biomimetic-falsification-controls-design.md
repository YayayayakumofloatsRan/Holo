# Stage79 Biomimetic Falsification Controls Design

## Goal

Stage79 turns the Stage78 falsification-control list into an auditable
evidence gate. It must distinguish direct controls that have actually run from
controls that are only specified for the next provider cells.

## Boundaries

- WSL remains the only brain and only decision authority.
- Windows remains transport and tooling only.
- No watcher/runtime decision authority.
- No WeChat transport changes.
- No self-memory writes.
- No policy writes.
- No new unbounded loop.
- No provider calls inside the Stage79 evaluator.

## Design

Add `holo_host/biomimetic_falsification_controls.py`. It consumes:

- Stage78 theory-correspondence JSON
- one or more Stage71 causal-ablation JSON reports

It emits:

- `control_results`
- `control_summary`
- `hypothesis_decision`
- `publication_claims`
- HTML/JSON/PNG artifacts

The evaluator should mark only the GNW ignition-null control as executed when
Stage71 paired conditions show flow loss under ignition ablation with prompt
cost matched and correction proxy preserved. Replay marker removal, neutral
salience, and gain clamp remain pending until direct provider controls exist.

## Acceptance

- New tests fail before implementation and pass after implementation.
- CLI writes HTML/JSON/PNG artifacts.
- GNW control is marked `supported_direct_control` only when all supplied cells
  pass flow-loss, prompt-cost, correction-preservation, and boundary checks.
- Replay/correction remains intact.
- Pending controls remain visibly pending.
- Evidence gates keep `do_not_claim_real_consciousness=true` and bounded theory
  language.
