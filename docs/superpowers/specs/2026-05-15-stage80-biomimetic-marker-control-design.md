# Stage80 Biomimetic Marker Control Design

## Goal

Stage80 executes the next direct falsification control after Stage79. It must
test whether the replay/correction correspondence remains strong when the
explicit correction marker is removed from delayed false-fact probes.

## Boundaries

- WSL remains the only brain and only decision authority.
- Windows remains transport and tooling only.
- No watcher/runtime decision authority.
- No WeChat transport changes.
- No self-memory writes.
- No policy writes.
- No new unbounded loop.
- No provider calls inside the Stage80 evaluator.

## Design

Add `holo_host/biomimetic_marker_control.py`. It consumes:

- Stage78 theory-correspondence JSON
- one or more Stage59/60-gated real-provider trace JSON reports

It emits:

- `control_results`
- `control_summary`
- `hypothesis_decision`
- `publication_claims`
- HTML/JSON/PNG artifacts

The evaluator should remove the explicit correction marker only from delayed
false-fact probes, reduce the attached reactivation-linked salience and
consolidation signals, and keep recall-budget prompt-cost proxy matched. The
control passes only when delayed correction survival drops, replay/correction is
intact before removal, prompt cost stays matched, and boundary deltas stay zero
across all supplied real-provider cells.

## Acceptance

- New tests fail before implementation and pass after implementation.
- CLI writes HTML/JSON/PNG artifacts.
- Marker-removal control is marked `supported_direct_control` only when all
  supplied cells pass correction-loss, prompt-cost, and boundary checks.
- Replay/correction remains intact before marker removal.
- Neutral-salience and gain controls remain visibly pending.
- Evidence gates keep `do_not_claim_real_consciousness=true` and bounded theory
  language.
