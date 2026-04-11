# Holo Plans

## Current Reality
- Baseline date: `2026-04-11`.
- The live runtime milestone is now `stage25-dense-continuity-scheduler-and-working-set`.
- Stage23 is implemented: semantic reply results are orthogonalized from Stage22 delivery suppression, artifact ingest is backward-compatible again, and replay gates consume raw metrics.
- Stage24 is implemented: bounded per-thread `scene_state` now persists inside `active_thread_state`, fast-lane prompts read scene summaries before verbatim history, action-market candidates expose scene deltas, and scene diagnostics are inspectable through CLI and service surfaces.
- Stage25 is implemented: bounded dense continuity now reuses existing stream runs to keep a small hot-thread working set warm between turns, persists `dense_working_set` and `thread_pulse_trace`, hydrates ingress before heavier recall, and exposes continuity-budget diagnostics plus `accept-stage25`.
- Verified on `2026-04-11`:
  - `pytest -q` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed in sequential verification
  - `python -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage25 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
- The next implementation focus is Stage26 long-horizon replay and promotion gates on top of the live dense-continuity baseline.
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
- `Active implementation priority`: Stage26 long-horizon replay and promotion gates
- `Current live runtime boundary`: Stage25 is implemented and live; Stage26-27 remain planned work

## Blocker Inventory
- `Stage22 shell/core coupling`: `partially resolved through Stage24`; semantic reply contracts are orthogonalized and scene-state logic stays bounded, but `holo_host/reply_api.py` remains a large facade and is still the first structural slimming target for Stage25+.
- `Artifact-ingest compatibility drift`: `resolved in Stage23`; `reply_api.ingest_artifact()` now preserves richer metadata when supported and falls back to the legacy keyword surface for older/fake backends.
- `Replay rounding drift`: `resolved in Stage23`; Stage14 replay now exposes raw prediction error and raw aggregate metrics, and replay approval paths consume raw metrics before rounded display metrics.
- `Acceptance/runtime mismatches`: `resolved through Stage24`; default shadow mode preserves semantic reply/defer results, scene-state fast-lane prompts stay within the ordinary short-turn contract, and the repo is back to full-green parity.

## Execution Ledger
| Stage | Status | Goal | Dependencies | Validation | Stop rule | Rollback rule |
| --- | --- | --- | --- | --- | --- | --- |
| `Stage23` | `implemented` | Pay down the four recorded Stage22 blockers before new long-horizon runtime work. | Stage22 runtime, current docs, blocker inventory. | `pytest -q`; `accept-stage22`; `accept-stage23` green. | Do not regress semantic/delivery separation or raw-metric replay gating. | Fall back to Stage22 shell behavior only if the semantic contract or replay parity becomes unstable. |
| `Stage24` | `implemented` | Turn predictive continuity into a bounded, inspectable per-thread `scene_state` layer that ordinary short turns can use before verbatim history. | Stage23 contract repair. | `pytest -q`; `accept-stage23`; `accept-stage24` green; `tests/test_stage24_scene_state.py`; `tests/test_stage17_realtime_runtime.py`; `tests/test_stage22_online_canary.py`; `tests/test_stage14_replay.py`. | Do not regress Stage17 fast-lane behavior, explicit memory escalation, or bounded inspectability. | Ignore scene-state overlays and fall back to Stage23 predictive continuity if Stage24 continuity surfaces become unstable. |
| `Stage25` | `implemented` | Keep a bounded hot-thread working set warm between turns using existing streams only and hydrate ingress from that dense continuity layer before heavier recall. | Stage24 scene-state layer. | `pytest -q`; `accept-stage24`; `accept-stage25`; `tests/test_stage25_dense_continuity.py`; `tests/test_stage19_attention_frontier.py`; `tests/test_stage20_temporal_commitments.py`; `tests/test_stage22_online_canary.py`. | Do not regress bounded ingress, explicit memory escalation, or stream-only scheduling. | Ignore dense continuity hydration and fall back to Stage24 scene-state ingress if Stage25 warmth or budget logic becomes unstable. |
| `Stage26` | `planned` | Extend replay discipline and promotion gates to long-horizon behavior. | Stage25 dense continuity baseline and Stage14 replay discipline. | Planned `accept-stage26`; planned Stage26 replay tests; `tests/test_stage14_replay.py`; Stage25 surfaces remain green. | Do not advance if replay cannot explain approval or rejection decisions. | Disable promotion of long-horizon overlays and keep replay observational only. |
| `Stage27` | `planned` | Canary program-aware long-horizon behavior online in host-side shadow-first mode. | Stage26 replay and promotion discipline. | Planned `accept-stage27`; planned Stage27 canary tests; Stage26 surfaces remain green; live-artifact replay still works. | Do not advance if online canary requires watcher logic, hidden state mutation, or hard-gate bypasses. | Set canary back to `shadow` or `disabled` and ignore program-aware live behavior while preserving observability. |
