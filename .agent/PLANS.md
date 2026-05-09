# Holo Plans

## Current Reality
- Baseline date: `2026-04-11`.
- The live runtime milestone is now `stage36-autonomous-inquiry-quality`.
- Stage23 is implemented: semantic reply results are orthogonalized from Stage22 delivery suppression, artifact ingest is backward-compatible again, and replay gates consume raw metrics.
- Stage24 is implemented: bounded per-thread `scene_state` now persists inside `active_thread_state`, fast-lane prompts read scene summaries before verbatim history, action-market candidates expose scene deltas, and scene diagnostics are inspectable through CLI and service surfaces.
- Stage25 is implemented: bounded dense continuity now reuses existing stream runs to keep a small hot-thread working set warm between turns, persists `dense_working_set` and `thread_pulse_trace`, hydrates ingress before heavier recall, and exposes continuity-budget diagnostics plus `accept-stage25`.
- Stage26 is implemented: bounded `task_world_object` plus `task_world_link` now persist inspectable task-world state across restarts, Stage22 `world_coupling_signal` is a compatibility projection over same-thread task-world visibility, and ingress can hydrate same-thread turns from bounded task-world state before heavier recall.
- Stage27 is implemented: long-horizon blackbox soak runs, scorecards, replay-on-live-artifacts, and blind evaluation packet export now exist as bounded operational surfaces in `QueueStore` and artifact directories without mutating self-memory.
- Stage28 is implemented as a bounded vertical slice: mind packets now expose `visual_field`, `situational_field`, and `stage28`; visual ingest preserves spatial/uncertainty metadata; prompt ordering uses situational fields before verbatim history; and action-market candidates expose inspectable Stage28 deltas.
- Stage29 is implemented as a unified bionic subject kernel with CLI as the first adapter: one bounded adapter turn produces an inspectable bionic capsule, records operational `bionic_agent_traces`, exposes bionic metrics, validates a synthetic WeChat adapter path, can use DeepSeek through the processor fabric, and now keeps internals split under `holo_host/bionic_kernel_parts/` behind the stable `holo_host.bionic_agent` facade.
- Stage30 is implemented as an explicit unified `subject_loop` contract over the bionic capsule: perception, working field, attention, inhibition, action market, generation, outcome appraisal, and state update are now visible in one bounded loop with hard invariants and no self-memory or policy mutation.
- Stage31 is implemented as an offline debt burn-down slice: adapter registry, controlled state-update gate, subject-loop trace/metrics diagnostics, bionic CLI helper extraction, and `accept-stage31`.
- Stage32 is implemented as an offline response-shaping slice: deterministic fallback generation now uses bounded query/action/continuity/situational context instead of a fixed template, exposes context-shaping metadata, and validates through `accept-stage32`.
- Stage33 is implemented as an offline provider/API contract slice: provider API surfaces are inspectable, `openai_compatible` uses chat-completions, and `accept-stage33` validates processor-fabric boundaries.
- Stage34 is implemented as an offline debt-registry and visual-readiness slice: current weak spots are classified, text-only providers cannot overclaim image support, and `accept-stage34` validates the boundary.
- Stage35 is implemented as an internal runtime-readiness slice: DeepSeek primary lanes, env-key presence, local config secret hygiene, and no-WeChat quiescence are machine-checkable through `accept-stage35`.
- Stage36 is implemented as an autonomous-inquiry quality slice: deterministic bionic fallback text no longer uses label-template prefixes, asks at most one grounded question, exposes inquiry-quality metrics, and validates through `accept-stage36` without starting WeChat.
- Verified Stage34 on `2026-05-09`:
  - `pytest -q` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage34` passed
  - `python scripts/check_public_release_hygiene.py` passed
- Verified Stage35 on `2026-05-09`:
  - `pytest -q tests/test_stage35_internal_runtime_readiness.py` passed
  - `python -m holo_host --config .holo_host.toml show-internal-runtime-readiness` passed with redacted key status and no WeChat helper runtime
  - `python -m holo_host --config .holo_host.toml accept-stage35` passed
- Verified Stage36 on `2026-05-09`:
  - `pytest -q tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py tests/test_stage35_internal_runtime_readiness.py tests/test_stage34_debt_closure.py` passed
  - `python -m holo_host --config .holo_host.toml accept-stage36 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed
  - `pytest -q` passed with `293` tests
  - `python scripts/check_public_release_hygiene.py` passed
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
- The next implementation focus is explicit Stage37+ planning for real visual-provider integration, provider latency/cache soak, replay-backed facade slimming, replay-fixture breadth, or operator-approved live WeChat hardening; Holo remains WeChat-offline until live transport validation is explicitly approved.
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
- `Active implementation priority`: Stage37+ targeted debt repair for real visual-provider integration, provider latency/cache soak, replay-backed facade slimming, replay-fixture breadth, or operator-approved live WeChat hardening
- `Current live runtime boundary`: Stage36 is implemented in code as an offline autonomous-inquiry quality slice; no live transport, live model call during acceptance, or self-memory mutation was added

## Blocker Inventory
- `Stage22 shell/core coupling`: `partially resolved through Stage24 and classified by Stage34`; semantic reply contracts are orthogonalized and scene-state logic stays bounded, but `holo_host/reply_api.py` remains large bounded structural debt that must only be split behind dedicated compatibility tests.
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
| `Stage30` | `implemented` | Add an explicit unified subject-loop contract over the bionic capsule, from perception through state update. | Stage29 bionic kernel and adapter-safe capsule pipeline. | `pytest -q`; `accept-stage30`; `tests/test_stage30_subject_loop.py`. | Do not let the loop mutate self-memory, policy sediment, Mind Graph, transport, or scheduler state. | Ignore `subject_loop` payloads and fall back to Stage29 capsule semantics. |
| `Stage31` | `implemented` | Burn down immediate Stage29/30 architecture debt: adapter registry, controlled state-update gate, subject-loop diagnostics, and bionic CLI helper extraction. | Stage30 subject-loop contract. | `pytest -q`; `accept-stage31`; `tests/test_stage31_debt_burndown.py`. | Do not add live transport, self-memory writes, raw provider calls, or unbounded loop behavior. | Fall back to Stage30 subject-loop payloads and keep adapter registry observational only. |
| `Stage32` | `implemented` | Burn down immediate template-pressure debt by replacing the fixed deterministic fallback phrase with bounded context-shaped response generation. | Stage31 adapter and state-gate baseline. | `pytest -q`; `accept-stage32`; `tests/test_stage32_response_shaping.py`. | Do not add live transport, self-memory writes, raw provider calls, or a hidden planner. | Fall back to Stage31 generation behavior only if response-shaping metrics or deterministic fallback stability regress. |
| `Stage33` | `implemented` | Burn down provider/API compatibility ambiguity by making provider API surfaces explicit and correcting OpenAI-compatible calls to chat-completions. | Stage32 response-shaping baseline and processor fabric. | `pytest -q`; `accept-stage33`; `tests/test_stage33_provider_contracts.py`; `tests/test_processor_fabric.py`. | Do not add direct model calls outside provider classes, live transport, or self-memory writes. | Fall back to Stage32 bionic behavior and disable provider-contract acceptance if provider surfaces become ambiguous. |
| `Stage34` | `implemented` | Close offline-verifiable technical debt by adding a classified debt registry and bounded visual-provider readiness gate. | Stage33 provider contract baseline. | `pytest -q`; `accept-stage34`; `tests/test_stage34_debt_closure.py`; `tests/test_stage33_provider_contracts.py`. | Do not start live transport, mutate self-memory, overclaim text-provider image support, or hide weak spots outside the registry. | Fall back to Stage33 provider-contract acceptance and keep live-only debts as explicit external preconditions. |
| `Stage35` | `implemented` | Make the internal DeepSeek-backed runtime startup machine-checkable without starting WeChat. | Stage34 debt registry and local DeepSeek config. | `pytest -q`; `accept-stage35`; `tests/test_stage35_internal_runtime_readiness.py`. | Do not embed keys in config, start WeChat, perform live model calls during acceptance, or expose unredacted secrets. | Fall back to Stage34 gates and keep Holo internal-only until readiness passes again. |
| `Stage36` | `implemented` | Close autonomous-inquiry formatting debt in the offline bionic kernel while preserving action-market-first generation. | Stage35 internal runtime readiness and Stage32 response shaping. | `pytest -q`; `accept-stage36`; `tests/test_stage36_inquiry_quality.py`. | Do not reintroduce label-template inquiry, ask multiple ungrounded questions, start transport, or add a hidden planner. | Fall back to Stage35 internal readiness and Stage32 shaping; keep inquiry debt visible until Stage36 passes again. |

## Release Hygiene Ledger
| Surface | Status | Rule | Validation |
| --- | --- | --- | --- |
| Public GitHub publish surface | `active` | Track runtime code, architecture docs, examples, and tests; do not track `.subject.local.md`, private subject seed/profile files, live memory JSONL, runtime DBs, transport receipts, or canary artifacts. | `python scripts/check_public_release_hygiene.py`; `pytest -q tests/test_public_release_hygiene.py` |
