# Stage78 Biomimetic Theory Correspondence Design

## Goal

Stage78 formalizes the neuroscience theory correspondence that was missing from
the Stage70-77 evidence chain. The output is a falsifiable matrix that maps
current Holo variables to GNW, hippocampal indexing/CLS, predictive processing,
and neuromodulatory gain, with explicit controls that can disconfirm each
mapping.

## Non-Negotiable Boundaries

- WSL remains the only brain and only decision authority.
- Windows remains transport and tooling only.
- No watcher/runtime decision authority.
- No WeChat transport changes.
- No self-memory writes.
- No policy writes.
- No new unbounded loop.
- No provider calls inside the Stage78 theory evaluator.

## Design

Add a read-only evaluator, `holo_host/biomimetic_theory_correspondence.py`, that
consumes the Stage77 model-family stability JSON. It should emit:

- `theory_correspondence_matrix`
- `theory_summary`
- `hypothesis_decision`
- `publication_claims`
- `falsification_controls`
- HTML/JSON/PNG artifacts

Each theory row must contain:

- `theory_id`
- `neuroscience_theory`
- `literature_anchor`
- `holo_variables`
- `measurable_predictions`
- `disconfirming_controls`
- `support_status`
- `falsifiable`
- `evidence_summary`

## Theory Mappings

- GNW maps to `global_workspace_ignition`, `ignition_to_reply_coupling`, and
  flow-loss reduction.
- Hippocampal indexing/CLS maps to `correction_reactivation_marker`,
  hippocampal reactivation, and replay/correction residual compression.
- Predictive processing maps to correction markers, precision-like pressure,
  correction survival, and prompt-cost bounds.
- Neuromodulatory gain maps to neuromodulator coupling, salience gate,
  thalamic gain, and uncertainty monitor.

## Acceptance

- New tests fail before implementation and pass after implementation.
- The evaluator classifies the current Stage77 evidence as a bounded preprint
  candidate, not a consciousness proof.
- Every theory row has at least two measurable predictions and two
  disconfirming controls.
- CLI writes HTML/JSON/PNG artifacts.
- Docs, handoff, and roadmap record the current interpretation and next
  targeted controls.
