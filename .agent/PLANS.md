# Holo Plans

## Current Reality
- Baseline date: `2026-04-11`.
- The live runtime milestone is now `stage63-cache-inheritance-spine`.
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
- Stage37 is implemented as a bionic self-eval and capability-honesty slice: same-thread bionic trace continuity is prompt-visible, text-provider image overclaiming is guarded, non-executable self-eval actions fall back to speech candidates, and provider-backed output is question/markdown bounded.
- Stage38 is implemented as a visual-provider bridge slice: explicit bionic CLI image input routes through `image_understand`, image-capable provider metadata is persisted with visual memory, and text-only generation consumes visual summaries without overclaiming direct raw image access.
- Stage39 is implemented as a bionic Turing benchmark slice: internal CLI probes now score continuity reference, mechanism-leakage prevention, naturalness, question bounds, context grounding, and non-empty speech without starting WeChat.
- Stage40 is implemented as a bionic brain OS harness slice: internal CLI/API `brain-run` now records operational context bundles, phase traces, action-market tool gates, verification evidence, DeepSeek V4 profile metadata, and agent-eval scorecards without starting WeChat or mutating self-memory.
- Stage41 is implemented as a complete controlled engineering-agent slice: internal CLI/API `engineering-run` can observe, compile context, deliberate, gate tool actions, execute read/search/test/write actions under explicit authority, verify outcomes, and persist inspectable operational traces without starting WeChat or mutating self-memory.
- Stage42 is implemented as an isolated bionic user-simulation performance slice: internal CLI/API `run-bionic-user-sim` repeatedly probes first-time-user dialogue quality and high-intensity bionic pressure points, scores continuity, naturalness, capability honesty, mechanism leakage, repetition, and latency, persists only operational `agent_eval_runs`, and exposes observational `bionic_state` in bionic capsules.
- Stage43 is implemented as a bounded motivational-dynamics slice: bionic capsules expose replay-stable `motivational_field` with internal pressure variables, diffuse attention, attention center, bounded stochasticity, and action-market-only score deltas without adding a second decision layer.
- Stage44 is implemented as latency-preserving recall demotion: ordinary non-explicit recall pressure no longer blocks on Windows history refresh or reconstruction, while explicit memory/history requests keep full recall.
- Stage45 is implemented as biomimetic grounding and context scheduling: current-image overclaims are guarded, explicit reminder promises bind to temporal state, and processor context scheduling exposes stable/volatile prompt digests plus exact-response cache diagnostics.
- Stage46 is implemented as a bionic boundary stress and provider-substrate diagnostics slice: `run-bionic-boundary-stress` and `show-bionic-boundary-stress-scorecard` persist operational high-intensity scorecards, DeepSeek-to-Codex fallback uses provider-specific models, and local DeepSeek availability now requires the configured API key env var.
- Stage47 is implemented as a provider-substrate conflict monitor: `show-provider-substrate-status` and `/provider-substrate-status` expose active-provider, lane-primary, fallback, and provider/model mismatch conflicts, and Stage46 scorecards now downgrade conflicted runs before treating them as biomimetic evidence.
- Stage48 is implemented as a biomimetic memory scheduler: working memory, hippocampal indices, cortical schema, salience gates, and diagnostic consolidation targets are separated without adding a new memory store or self-memory write path.
- Stage49 is implemented as a memory prompt diet and reconstruction-priority repair: scheduler-owned memory replaces duplicate legacy volatile blocks, while reconstruction summaries and anchors are promoted inside the hippocampal budget.
- Stage50 is implemented as a dynamic compression audit: scheduler-owned prompt lines expose raw/selected/dropped counts, compression ratio, protected labels, and protected-drop status in context scheduling and Stage46 debug evidence.
- Stage51 is implemented as bionic memory lifecycle and consciousness flow: diagnostic consolidation/replay/forgetting gates and prompt-only sensory/affective/memory/goal phase ordering are exposed while keeping `self_memory_write=false`, `background_loop_allowed=false`, and `user_visible=false`.
- Stage52 is implemented as scheduler-owned prompt fusion: Stage51 lifecycle/flow prompt material is compacted into a single `Bionic Dynamic Frame`, keeping lifecycle/flow packet/debug evidence while reducing live DeepSeek miss tokens versus Stage51.
- Stage53 is implemented as an upstream MCP tool substrate: reviewed stdio MCP servers can be discovered/called/read as bounded external observations through CLI and the Stage41 engineering-agent action market.
- Stage54 is implemented as consciousness-flow visualization: Stage46 stress traces can be rendered into HTML/JSON/PNG compute heatmaps, high-dimensional compute vectors, turn-to-turn movement, attention-block allocation proxies, and internal/output token ratios.
- Stage55 is implemented as a consciousness-manifold observatory: Stage46/54 traces can be transformed into delay embeddings, Poincare-style section families, local dynamics, hyperbolic proxies, recurrence-loop candidates, and topology cycle-rank proxies.
- Stage56 is implemented as a dimensional-lift observatory: Stage55 vectors are lifted from 12 dimensions into 138 residual/dynamics/lag/interaction dimensions, with residual fast-channel preservation, multi-plane projections, effective-rank probes, sample-adequacy diagnostics, and section-stability checks.
- Stage57 is implemented as geometry calibration: recent Stage46 runs can be compared in Stage56 lifted space through pairwise geometry distances, baseline-relative perturbation response, predictive probes, and evidence gates that keep manifold claims blocked until trace depth is sufficient.
- Stage58 is implemented as a long-form geometry lab: recent Stage46 seeds can generate bounded Stage46-compatible surrogate long traces with perturbation labels, feed them through Stage57 calibration, and export artifacts while keeping real-manifold claims blocked until real provider long-form evidence exists.
- Stage59 is implemented as a provider long-form trace runner: `run-consciousness-provider-trace` can dry-run or execute strict provider long-form simulations through Holo's subject runtime, defaults execute mode to shadow state, writes HTML/JSON/PNG plus JSONL journals, supports resume, and feeds collected real provider traces into Stage57 calibration.
- Stage60 is implemented as a recoverable long-run provider trace campaign orchestrator: `run-consciousness-trace-campaign` can dry-run or execute multi-model Stage59 cells, defaults executed cells to shadow state, writes campaign HTML/JSON/PNG plus manifest/events, supports per-cell resume, aggregates token/cache/provider provenance, ranks models, and blocks major-breakthrough claims until replicated real-provider trace depth and Stage57 gates pass.
- Stage61 is implemented as a high-throughput bionic simulation lab: `run-bionic-simulation-lab` generates Stage46-compatible surrogate interaction traces, captures internal token/cache/latency/memory/consciousness-flow/tool/grounding telemetry, writes HTML/JSON/PNG plus per-turn JSONL, feeds Stage57 calibration, and emits non-auto-applied improvement backlog items.
- Stage62 is implemented as a bionic capability observatory: `evaluate-bionic-capability-observatory` converts Stage61 telemetry into capability scorecards, forward explainability chains, reverse-engineered bottlenecks, and non-auto-applied intervention targets with HTML/JSON/PNG artifacts.
- Stage63 is implemented as a cache inheritance spine: the bionic memory scheduler now emits a stable cortical cache spine, context scheduling and Stage46 compact debug preserve cache-inheritance evidence, and Stage61 simulation responds to larger stable-prefix evidence while keeping current turns and per-turn recall dynamic.
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
- Verified Stage37 on `2026-05-09`:
  - `pytest -q tests/test_stage37_bionic_self_eval.py tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py tests/test_stage35_internal_runtime_readiness.py` passed
  - `python -m holo_host --config .holo_host.toml accept-stage37 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed
  - `pytest -q` passed with `298` tests
  - `python scripts/check_public_release_hygiene.py` passed
  - `git diff --check` reported no whitespace errors
- Verified Stage38 on `2026-05-10`:
  - `pytest -q tests/test_stage38_visual_provider_bridge.py tests/test_stage37_bionic_self_eval.py tests/test_stage34_debt_closure.py tests/test_stage28_multimodal_homeostatic_kernel.py tests/test_stage29_bionic_cli_agent.py` passed
  - `python -m holo_host --config .holo_host.toml accept-stage38 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed
  - `pytest -q` passed with `301` tests
  - `python scripts/check_public_release_hygiene.py` passed
  - `git diff --check` reported no whitespace errors
- Verified Stage39 on `2026-05-10`:
  - `pytest -q tests/test_stage39_bionic_turing_benchmark.py tests/test_stage38_visual_provider_bridge.py tests/test_stage37_bionic_self_eval.py tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py` passed
  - `python -m holo_host --config .holo_host.toml accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed
  - `python -m holo_host --config .holo_host.toml show-bionic-turing-scorecard --thread-key cli:TestUser --chat-name TestUser --channel cli` passed with scorecard status `pass`
  - `pytest -q` passed with `306` tests
  - `python scripts/check_public_release_hygiene.py` passed
  - `git diff --check` reported no whitespace errors
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
- The next implementation focus is reducing dynamic prompt churn after Stage63, then re-running Stage61/62 for telemetry deltas and confirming important gains with a budget-approved Stage60 real-provider campaign.
- Verified on `2026-05-10`: exact packet-cache reuse works on tight repeated live `/inspect-mind` probes, but homeostasis/self-model cache deficits were over-reported from zero-sample or stale cache snapshots. Post-Stage39 cache diagnostics now require a packet-cache sample floor and rebase cache-class deficits from live cache stats before reporting `cache_coldness` or `cache_reuse_weak`.
- Post-Stage39 provider-response caching is implemented in the processor fabric: `responses`, `openai_compatible`, and `deepseek` can reuse exact stateless text API responses through QueueStore, while `codex_cli`, image tasks, memory-writeback tasks, and shadow-write/operator tasks bypass the cache.
- Verified post-Stage39 provider-response cache repair on `2026-05-10`: `pytest -q tests/test_processor_fabric.py tests/test_cache_diagnostics.py tests/test_stage33_provider_contracts.py tests/test_stage35_internal_runtime_readiness.py tests/test_stage37_bionic_self_eval.py tests/test_stage38_visual_provider_bridge.py tests/test_stage39_bionic_turing_benchmark.py` passed, `pytest -q` passed with `312` tests, `accept-stage39` passed, `show-provider-status` exposed `response_cache.enabled=true`, public-release hygiene passed, and `git diff --check` reported no whitespace errors.
- Verified post-Stage39 self-dialogue Turing repair on `2026-05-10`: internal offline `agent-run` probes covered missing prior context, irritation handling, image honesty, visible-context honesty, anti-template replies, exact-memory boundaries, and revision repair with no mechanism leakage; a real DeepSeek provider probe hit the response cache and was guarded back to plain language; `pytest -q` passed with `322` tests; `accept-stage39` passed; public-release hygiene passed; `git diff --check` reported no whitespace errors.
- Verified Stage40 on `2026-05-10`:
  - `pytest -q tests/test_stage40_context_compiler.py tests/test_stage40_bionic_brain_harness.py tests/test_stage40_deepseek_v4_profile.py tests/test_stage40_agent_eval.py` passed
  - `python -m holo_host --config .holo_host.toml brain-run --goal "stage40 smoke" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2` passed
  - `python -m holo_host --config .holo_host.toml run-agent-eval --suite stage40` passed
  - `python -m holo_host --config .holo_host.toml accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed with the user-level `DEEPSEEK_API_KEY` loaded into the process environment
  - `python -m holo_host --config .holo_host.toml accept-stage40 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed with the user-level `DEEPSEEK_API_KEY` loaded into the process environment
  - `pytest -q` passed with `331` tests
  - `python scripts/check_public_release_hygiene.py` passed
  - `git diff --check` reported no whitespace errors
- Verified Stage41 on `2026-05-10`:
  - `pytest -q tests/test_stage41_engineering_agent.py` passed with `6` tests
  - `python -m holo_host --config .holo_host.toml engineering-run --goal "stage41 smoke" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2` passed
  - `python -m holo_host --config .holo_host.toml engineering-trace --trace-id 38` passed
  - `python -m holo_host --config .holo_host.toml show-engineering-agent-metrics --limit 5` passed
  - `python -m holo_host --config .holo_host.toml accept-stage41 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed with the user-level `DEEPSEEK_API_KEY` loaded into the process environment
  - `pytest -q` passed with `337` tests
  - `python scripts/check_public_release_hygiene.py` passed
  - `git diff --check` reported no whitespace errors
- Verified Stage42 on `2026-05-10`:
  - `pytest -q tests/test_stage42_bionic_user_sim.py tests/test_stage41_engineering_agent.py tests/test_stage39_bionic_turing_benchmark.py` passed with `25` tests
  - `python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:TestUser --chat-name TestUser --channel cli --offline` passed with scorecard status `pass`
  - `python -m holo_host --config .holo_host.toml show-bionic-user-sim-scorecard --suite novice_intro` passed
  - `python -m holo_host --config .holo_host.toml accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed
  - `pytest -q` passed with `340` tests
  - `python scripts/check_public_release_hygiene.py` passed
  - `git diff --check` reported no whitespace errors
- Verified Stage42 bionic-state hardening on `2026-05-10`:
  - `pytest -q tests/test_stage42_bionic_user_sim.py` passed with `9` tests
  - `pytest -q tests/test_stage39_bionic_turing_benchmark.py tests/test_stage42_bionic_user_sim.py` passed with `25` tests
  - `pytest -q` passed with `346` tests
  - `python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:FreeUser --chat-name FreeUser --channel cli --scenario free_dialogue --turns 12 --offline` passed with scorecard status `pass`, `issue_count=0`, and no WeChat transport start
  - `python -m holo_host --config .holo_host.toml accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed with `bionic_state_visible=true`
  - `python scripts/check_public_release_hygiene.py` passed
  - `git diff --check` reported no whitespace errors
- Verified Stage43 on `2026-05-11`:
  - `pytest -q tests/test_stage29_bionic_cli_agent.py tests/test_stage39_bionic_turing_benchmark.py tests/test_stage42_bionic_user_sim.py tests/test_stage43_motivational_dynamics.py` passed with `43` tests
  - `python -m holo_host --config .holo_host.toml accept-stage43 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed with `motivational_field_replay_stable=true`, `bounded_stochasticity=true`, and `bounded_action_delta=true`
  - `pytest -q` passed with `351` tests
  - `python scripts/check_public_release_hygiene.py` passed
  - `git diff --check` reported no whitespace errors
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
- `Latest engineering handoff`: `docs/ENGINEERING_HANDOFF_STAGE63.md`
- `Architecture reference`: `docs/HOLO_ARCHITECTURE_MAP.md`
- `Roadmap registry`: `docs/ROADMAP_REGISTRY.md`
- `Public release hygiene`: `docs/PUBLIC_RELEASE_HYGIENE.md`
- `Active implementation priority`: Stage63 follow-up dynamic prompt churn reduction, then Stage61/62 telemetry delta and Stage60 real-provider confirmation
- `Current live runtime boundary`: Stage63 is implemented as a prompt-scheduling and diagnostic cache-inheritance spine; no provider call, live transport, transport authority change, live self-memory mutation, default repo-write authority, direct runtime decision authority, downstream MCP server, unbounded loop, or second decision layer was added
- `New-thread resume point`: branch `codex/stage29-bionic-cli-agent`, Stage63 handoff in `docs/ENGINEERING_HANDOFF_STAGE63.md`

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
| `Stage37` | `implemented` | Repair observed bionic self-eval failures around context continuity, capability honesty, and non-speech empty replies. | Stage36 inquiry quality and Stage35 internal readiness. | `pytest -q`; `accept-stage37`; `tests/test_stage37_bionic_self_eval.py`. | Do not invent continuity, overclaim image support, bypass action-market-first, start transport, or add a hidden planner. | Fall back to Stage36 inquiry quality and keep capability-honesty failures visible until Stage37 passes again. |
| `Stage38` | `implemented` | Route explicit bionic CLI image input through image-capable `image_understand` and consume visual-memory summaries without text-provider overclaiming. | Stage37 capability honesty and Stage28 visual memory. | `pytest -q`; `accept-stage38`; `tests/test_stage38_visual_provider_bridge.py`. | Do not start WeChat, add transport authority, bypass processor fabric, or claim direct image reading from text-only providers. | Fall back to Stage37 honesty guard and require explicit `ingest-image`/visual-memory before visual claims. |
| `Stage39` | `implemented` | Add an internal bionic Turing scorecard and use it to reduce mechanism leakage, continuity reset, formulaic fallback text, and theatrical prompt pressure. | Stage38 visual-provider bridge and Stage37 capability honesty. | `pytest -q`; `accept-stage39`; `tests/test_stage39_bionic_turing_benchmark.py`. | Do not treat the scorecard as live human validation, add transport authority, mutate self-memory, or create a second decision layer. | Fall back to Stage38 visual-provider bridge and keep Stage39 scoring disabled until the benchmark is repaired. |
| `Stage40` | `implemented` | Add a bounded bionic brain OS harness for CLI/API agent work: context compilation, DeepSeek V4 profiles, action-market-gated tool loop, verification, operational traces, and agent eval. | Stage39 bionic Turing benchmark, processor fabric, QueueStore operational storage. | `pytest -q`; `accept-stage39`; `accept-stage40`; `tests/test_stage40_context_compiler.py`; `tests/test_stage40_bionic_brain_harness.py`; `tests/test_stage40_deepseek_v4_profile.py`; `tests/test_stage40_agent_eval.py`. | Do not start WeChat, mutate self-memory, bypass action-market gating, allow repo/runtime writes by default, or include private sources in context bundles. | Disable Stage40 brain commands from operator workflows and fall back to Stage39 bionic kernel surfaces while retaining operational tables. |
| `Stage41` | `implemented` | Turn Stage40 into a complete controlled engineering agent with CLI/API tool loops, explicit repo-write authority, verification evidence, trace inspection, and metrics. | Stage40 brain OS harness, processor fabric, QueueStore operational storage. | `pytest -q`; `accept-stage40`; `accept-stage41`; `tests/test_stage41_engineering_agent.py`. | Do not start WeChat, mutate self-memory, bypass action-market gating, read or write private/runtime paths, or allow repo writes without explicit operator authority. | Disable Stage41 engineering commands from operator workflows and fall back to Stage40 brain harness surfaces while retaining operational run evidence. |
| `Stage42` | `implemented` | Isolate the bionic first-time-user simulation as a repeatable performance test with continuity, naturalness, capability-honesty, mechanism-leakage, repetition, latency scoring, high-intensity bionic pressure probes, and observational `bionic_state`. | Stage41 engineering-agent baseline, Stage39 bionic Turing scoring, QueueStore operational eval storage. | `pytest -q`; `accept-stage41`; `accept-stage42`; `tests/test_stage42_bionic_user_sim.py`. | Do not start WeChat, mutate self-memory, write normal bionic traces, or let benchmark scores or `bionic_state` become runtime decision authority. | Keep Stage42 evidence operational-only, disable user-sim commands from operator workflows if isolation regresses, and fall back to Stage41 engineering-agent surfaces. |
| `Stage43` | `implemented` | Add a bounded motivational-dynamics field over the bionic kernel: pressure variables, diffuse attention, attention-center selection, replay-stable stochasticity, and action-market-only score deltas. | Stage42 bionic-state surface, Stage29 bionic kernel, action-market-first contract. | `pytest -q`; `accept-stage42`; `accept-stage43`; `tests/test_stage43_motivational_dynamics.py`. | Do not let motivation become action authority, self-memory mutation, live transport, hidden planner state, or unbounded stochastic behavior. | Ignore `motivational_field` overlays and fall back to Stage42 bionic-state surfaces if boundedness or replay stability regresses. |

## Release Hygiene Ledger
| Surface | Status | Rule | Validation |
| --- | --- | --- | --- |
| Public GitHub publish surface | `active` | Track runtime code, architecture docs, examples, and tests; do not track `.subject.local.md`, private subject seed/profile files, live memory JSONL, runtime DBs, transport receipts, or canary artifacts. | `python scripts/check_public_release_hygiene.py`; `pytest -q tests/test_public_release_hygiene.py` |
