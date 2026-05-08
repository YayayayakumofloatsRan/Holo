# Holo Plans

## Current Reality
- Baseline date: `2026-04-11`.
- The live runtime milestone is now `stage29-bionic-subject-kernel`.
- Stage23 is implemented: semantic reply results are orthogonalized from Stage22 delivery suppression, artifact ingest is backward-compatible again, and replay gates consume raw metrics.
- Stage24 is implemented: bounded per-thread `scene_state` now persists inside `active_thread_state`, fast-lane prompts read scene summaries before verbatim history, action-market candidates expose scene deltas, and scene diagnostics are inspectable through CLI and service surfaces.
- Stage25 is implemented: bounded dense continuity now reuses existing stream runs to keep a small hot-thread working set warm between turns, persists `dense_working_set` and `thread_pulse_trace`, hydrates ingress before heavier recall, and exposes continuity-budget diagnostics plus `accept-stage25`.
- Stage26 is implemented: bounded `task_world_object` plus `task_world_link` now persist inspectable task-world state across restarts, Stage22 `world_coupling_signal` is a compatibility projection over same-thread task-world visibility, and ingress can hydrate same-thread turns from bounded task-world state before heavier recall.
- Stage27 is implemented: long-horizon blackbox soak runs, scorecards, replay-on-live-artifacts, and blind evaluation packet export now exist as bounded operational surfaces in `QueueStore` and artifact directories without mutating self-memory.
- Stage28 is implemented as a bounded vertical slice: mind packets now expose `visual_field`, `situational_field`, and `stage28`; visual ingest preserves spatial/uncertainty metadata; prompt ordering uses situational fields before verbatim history; and action-market candidates expose inspectable Stage28 deltas.
- Stage29 is implemented as a unified bionic subject kernel with CLI as the first adapter: one bounded adapter turn produces an inspectable bionic capsule, records operational `bionic_agent_traces`, exposes bionic metrics, validates a synthetic WeChat adapter path, and can use DeepSeek through the processor fabric.
- Verified Stage23-27 on `2026-04-11`:
  - `pytest -q` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key TestUser --chat-name TestUser --channel wechat` passed in sequential verification
  - `python -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key TestUser --chat-name TestUser --channel wechat` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key TestUser --chat-name TestUser --channel wechat` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat` passed
- Verified Stage28 on `2026-04-28`:
  - `pytest -q tests/test_stage28_multimodal_homeostatic_kernel.py` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage28 --thread-key TestUser --chat-name TestUser --channel wechat` passed
- The next implementation focus is post-Stage29 bionic workflow hardening and broader provider/API compatibility; Holo remains offline until restart and transport validation are explicitly approved.
- The durable planning pair for the next arc is `.agent/PLANS.md` plus `.agent/STAGE23_27_PROGRAM.md`.
- Public release hygiene now treats local subject-profile files and live memory as private deployment data. Git should track only `.example` templates and generic architecture docs.

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
- `Public release hygiene`: `docs/PUBLIC_RELEASE_HYGIENE.md`
- `Active implementation priority`: Stage29 bionic subject-kernel validation, provider compatibility, adapter hardening, and post-Stage29 re-plan
- `Current live runtime boundary`: Stage29 is implemented in code as an offline adapter-validated bionic subject kernel; Holo should remain offline until restart is explicitly approved

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
| `Stage26` | `implemented` | Replace cue-only world coupling with bounded task-world state that same-thread ingress can inspect and reuse before heavier recall. | Stage25 dense continuity baseline and existing Stage20/22/24 seams. | `pytest -q`; `accept-stage22`; `accept-stage25`; `accept-stage26`; `tests/test_stage26_task_world_state.py`; `tests/test_stage22_online_canary.py`; `tests/test_stage20_temporal_commitments.py`; `tests/test_stage14_replay.py`. | Do not regress Stage22 canary transport boundaries, Stage24/25 bounded ingress, or explicit recall escalation. | Ignore Stage26 task-world hydration and fall back to Stage25 dense+scene ingress while preserving inspectable task-world storage. |
| `Stage27` | `implemented` | Add a long-horizon blackbox soak harness, scorecard, blind evaluation export, and replay-first eligibility reporting for task-world-aware behavior. | Stage26 bounded task-world baseline, Stage22 canary traces, and Stage14 replay discipline. | `pytest -q`; `accept-stage22`; `accept-stage25`; `accept-stage26`; `accept-stage27`; `tests/test_stage27_blackbox_soak.py`; `tests/test_stage22_online_canary.py`; `tests/test_stage14_replay.py`. | Do not widen canary send rights, bypass replay or safety gates, or let observational evaluation mutate self-memory. | Keep Stage27 observational only, disable soak follow-up eligibility if replay evidence weakens, and defer any live long-horizon canary widening. |
| `Stage28` | `implemented` | Add a bounded multimodal situational-field layer so ordinary turns can ground inquiry in visual, scene, task-world, dense-continuity, temporal, and homeostatic state before verbatim history. | Stage27 observational baseline, Stage24 scene state, Stage25 dense continuity, Stage26 task-world state, and visual memory. | `pytest -q`; `accept-stage27`; `accept-stage28`; `tests/test_stage28_multimodal_homeostatic_kernel.py`. | Do not add a second brain, new loop family, transport decision logic, or provider call outside processor fabric. | Ignore Stage28 situational overlays and fall back to Stage27/26 packet surfaces while preserving visual-memory metadata and diagnostics. |
| `Stage29` | `implemented` | Add a unified bionic subject kernel with CLI as the first adapter, synthetic WeChat adapter validation, operational trace persistence, bionic metrics, DeepSeek provider support, and local acceptance without restarting Holo. | Stage28 situational fields, processor fabric, QueueStore operational storage. | `pytest -q`; `accept-stage29`; `tests/test_stage29_bionic_cli_agent.py`; `tests/test_processor_fabric.py`. | Do not start WeChat, add a second brain, bypass action-market-first, give adapters decision authority, or add raw provider calls outside processor fabric. | Ignore bionic trace surfaces and fall back to Stage28 runtime; keep DeepSeek as an optional provider only. |

## Release Hygiene Ledger
| Surface | Status | Rule | Validation |
| --- | --- | --- | --- |
| Public GitHub publish surface | `active` | Track runtime code, architecture docs, examples, and tests; do not track `.subject.local.md`, private subject seed/profile files, live memory JSONL, runtime DBs, transport receipts, or canary artifacts. | `python scripts/check_public_release_hygiene.py`; `pytest -q tests/test_public_release_hygiene.py` |
