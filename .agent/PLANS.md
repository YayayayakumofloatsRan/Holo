# Holo Plans

## Current Reality
- Baseline date: `2026-04-11`.
- The live runtime milestone is now `stage23-kernel-shell-orthogonalization-and-release-parity`.
- Stage23 is implemented: semantic reply results are orthogonalized from Stage22 delivery suppression, artifact ingest is backward-compatible again, and replay gates consume raw metrics.
- Verified on `2026-04-11`:
  - `pytest -q` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed in sequential verification
  - `python -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
- The next implementation focus is Stage24 bounded subject programs.
- The durable planning pair for the next arc is `.agent/PLANS.md` plus `.agent/STAGE23_27_PROGRAM.md`.

## Non-Negotiable Contracts
- Memory is the self.
- Processors remain replaceable; model calls stay inside the processor fabric.
- Transport remains eyes and hands only.
- Action-market-first deliberation remains the decision path.
- Do not add a second brain layer.
- Do not add a new unbounded always-on loop.
- Do not let runtime or operator flows hot-edit the live repo.
- Ordinary WeChat direct-message identity remains canonicalized as `wechat:<name>`.

## Active Program Index
- `Stage23-27 bootstrap program`: `.agent/STAGE23_27_PROGRAM.md`
- `Current live runtime handoff`: `HOLO_HANDOFF.md`
- `Architecture reference`: `docs/HOLO_ARCHITECTURE_MAP.md`
- `Roadmap registry`: `docs/ROADMAP_REGISTRY.md`
- `Active implementation priority`: Stage24 bounded subject programs
- `Current live runtime boundary`: Stage23 is implemented and live; Stage24-27 remain planned work

## Blocker Inventory
- `Stage22 shell/core coupling`: `partially resolved in Stage23`; semantic reply contracts are now orthogonalized from canary delivery suppression, but `holo_host/reply_api.py` is still a large facade and remains the first structural slimming target for Stage24+.
- `Artifact-ingest compatibility drift`: `resolved in Stage23`; `reply_api.ingest_artifact()` now preserves richer metadata when supported and falls back to the legacy keyword surface for older/fake backends.
- `Replay rounding drift`: `resolved in Stage23`; Stage14 replay now exposes raw prediction error and raw aggregate metrics, and replay approval paths consume raw metrics before rounded display metrics.
- `Acceptance/runtime mismatches`: `resolved in Stage23`; default shadow mode now preserves semantic reply/defer results while expressing suppression through `returned_action` and delivery fields, and the repo is back to full-green parity.

## Execution Ledger
| Stage | Status | Goal | Dependencies | Validation | Stop rule | Rollback rule |
| --- | --- | --- | --- | --- | --- | --- |
| `Stage23` | `implemented` | Pay down the four recorded Stage22 blockers before new long-horizon runtime work. | Stage22 runtime, current docs, blocker inventory. | `pytest -q`; `accept-stage22`; `accept-stage23` green. | Do not regress semantic/delivery separation or raw-metric replay gating. | Fall back to Stage22 shell behavior only if the semantic contract or replay parity becomes unstable. |
| `Stage24` | `planned` | Introduce bounded, inspectable subject programs. | Stage23 contract repair. | Planned `accept-stage24`; planned Stage24 regression tests; Stage23 surfaces remain green. | Do not advance if the design starts behaving like a second brain or requires a new always-on loop. | Ignore or empty the program surface without changing Stage23 behavior. |
| `Stage25` | `planned` | Couple artifacts, tool outcomes, deferred replies, and world cues into the same bounded program surface. | Stage24 program surface. | Planned `accept-stage25`; planned Stage25 regression tests; Stage24 surfaces remain green. | Do not advance if ingest surfaces fork into incompatible schemas again. | Disable progress reducers while preserving Stage24 read surfaces. |
| `Stage26` | `planned` | Extend replay discipline and promotion gates to long-horizon behavior. | Stage25 progress coupling and Stage14 replay baseline discipline. | Planned `accept-stage26`; planned Stage26 replay tests; `tests/test_stage14_replay.py`; Stage25 surfaces remain green. | Do not advance if replay cannot explain approval or rejection decisions. | Disable promotion of long-horizon overlays and keep replay observational only. |
| `Stage27` | `planned` | Canary program-aware long-horizon behavior online in host-side shadow-first mode. | Stage26 replay and promotion discipline. | Planned `accept-stage27`; planned Stage27 canary tests; Stage26 surfaces remain green; live-artifact replay still works. | Do not advance if online canary requires watcher logic, hidden state mutation, or hard-gate bypasses. | Set canary back to `shadow` or `disabled` and ignore program-aware live behavior while preserving observability. |
