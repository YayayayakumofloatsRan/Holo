# Kernel v3 Progress: Retrieval Loop Hardening

Date: 2026-06-03

## Scope

This iteration hardened the live retrieval path and the agent loop feedback surface.

Kernel v3 remains host-owned:

- the model proposes actions;
- the host validates policy and schemas;
- tools execute through the registry/operator layer;
- observations, evidence, citations, and decisions are journaled;
- finalization is host-gated by workloop and evidence sufficiency rules.

## Changes

- Network budget guard no longer blocks a retrieval action only because the payload declares a large `max_fetches`; the tool is allowed to run while budget remains, and actual fetch attempts become observations for the loop.
- Context packaging now compacts retrieval reports, mission context, thread RAG context, and static capability/source metadata before sending planner/evaluator prompts.
- Capability/state-space visibility is preserved, but prompt-facing metadata omits large schemas and repeated execution history.
- SEC source ranking is intent-sensitive:
  - general finance fact queries prefer companyfacts;
  - submissions/accession/primaryDocument queries prefer submissions metadata.
- SEC companyfacts extraction now emits complete structured fact lines as spans, preserving `concept`, `metric`, `label`, `val`, period, form, filing date, and accession.
- Target entity detection ignores direct URL tokens and SEC/XBRL concept names, so direct companyfacts URLs are not rejected as target-entity mismatches.

## Validation

Deterministic regression:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_*.py
```

Result:

```text
637 passed
```

Live checks:

- DeepSeek/live agent smoke completed once with SEC companyfacts evidence and a final answer.
- Direct live retrieval against `https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json` succeeded with:
  - `status=sufficient`;
  - 4 evidence items;
  - 4 citation items;
  - primary SEC source authority.

## Remaining Issues

- `holo-v3 agent` is still not fully streaming in non-console mode; long live tasks can leave the terminal quiet until completion.
- Deep finance research still needs stronger strategy control so the planner reliably moves from discovery metadata to final numeric evidence without repeated weak queries.
- The answer layer can still be too brief for broad research unless the answer profile explicitly demands a report-depth output.
