# Roadmap Registry

This registry exists so Holo planning does not collapse into a single forced choice every stage.

## Primary Track
- autobiographical continuity
- long-horizon goals
- identity/goal-led deliberation

## Secondary Tracks
- richer desire shaping
- stronger negotiated will

## Implemented Subject-Runtime Arc

This arc follows Stage17 thread-resident realtime runtime. Its purpose is to make Holo more continuous without turning continuity into a second brain or an unbounded loop.

Stage18: dual-speed reflex and predictive continuity
- Implemented bounded next-turn predictive continuity inside `ActiveThreadState`.
- Uses existing `micro_fast` only as a conservative generation lane after action-market selection.
- Keeps explicit memory/history/factual requests on recall escalation paths.

Stage19: bounded background continuity and attention frontier
- Implemented as a bounded Mind Graph `attention_frontier` fed only by `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`.
- Ingress hydrates same-thread active state from one frontier row before heavier recall.
- Bound entries by count, expiry, evidence refs, and canonical thread key; do not expand initiative sending rights.

Stage20: temporal commitments and interruption recovery
- Implemented as bounded Mind Graph `temporal_subject_state` plus `QueueStore.jobs` dedupe.
- Persists deferrals, promises, interrupted actions, restart-safe resume candidates, and due followup keys by canonical thread key.
- Routes recovery through action-market candidate metadata; temporal state never sends directly.

Stage21: policy sedimentation and negotiated will
- Implemented as Mind Graph `policy_sediment` rows with candidate/promoted/rejected/rolled-back statuses.
- Promotion is replay-gated and support/confidence/evidence bounded.
- Promoted rows bias action-market scoring only; hard policy gates, send permission, owner shutdown, secrets, auth, and safety boundaries remain outside sediment scope.

Stage22: bounded blackbox online canary
- Implemented as host-side `shadow` by default with `canary_live` behind whitelist, rate limits, rollback switch, and existing outbound policy.
- Records operational `online_canary_traces` and artifacts for daily Stage14 replay-on-live-artifacts.
- Hydrates bounded Mind Graph `world_coupling_signal` cues as same-thread perception inputs only; cues do not select actions or trigger recall by themselves.

Stage23: kernel/shell orthogonalization and release parity
- Implemented as a semantic-versus-delivery split: Stage22 suppression no longer rewrites the subject action contract and instead only changes transport-facing `returned_action` plus delivery fields.
- Restores full-green release parity by making artifact ingest backward-compatible again and by pushing replay gating onto raw metrics while rounded aggregates stay reporting-only.
- Keeps Stage22 shadow-first safety boundaries, live-artifact replay, rollback, rate limits, and canary traces intact.

Stage24: scene-state continuity layer
- Implemented as a bounded per-thread `scene_state` stored inside `active_thread_state`.
- Makes ordinary short turns prefer compact scene summaries and response sketches before verbatim history while keeping explicit memory/history/factual turns on escalation paths.
- Adds inspectable scene diagnostics and bounded scene deltas in action-market scoring without introducing a second brain or a new always-on loop.

Stage25: dense continuity scheduler and working set
- Implemented as a bounded `dense_working_set` plus `thread_pulse_trace` rebuilt only from `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`.
- Keeps a small hot-thread working set warm between turns, applies inspectable per-thread pulse budgets and cooldowns, and hydrates ingress before heavier recall.
- Does not add a new loop family, watcher-side decision logic, or background heavy recall.

Stage26: bounded task-world state
- Implemented as bounded Mind Graph `task_world_object` plus `task_world_link` storage for file, task, schedule, image-summary, and person objects.
- Keeps Stage22 `world_coupling_signal` as a compatibility projection while same-thread ingress hydrates from explicit task-world objects before heavier recall.
- Links temporal commitments and resume pressure into inspectable task-world state without adding a new decision layer or heavy-recall trigger.

Stage27: long-horizon blackbox soak and blind evaluation harness
- Implemented as an observational `QueueStore` soak-run surface plus artifact export under the Stage22 canary tree.
- Computes long-horizon scorecards, replays live artifacts, and exports blind transcript or comparison packets without mutating self-memory or widening runtime autonomy.
- Keeps online long-horizon canary deferred; Stage27 is replay-first and operational-only.

Stage28: multimodal homeostatic kernel
- Implemented as bounded packet-derived `visual_field`, `situational_field`, and `stage28` surfaces over existing visual memory, scene state, dense continuity, task-world state, temporal pressure, and homeostatic/affective pressure.
- Preserves richer image-understanding metadata and renders situational grounding before verbatim history for ordinary hot-path turns.
- Adds inspectable action-market `stage28_delta`, `stage28_rationale`, and `stage28_grounding_order` without adding a second brain, loop family, or transport decision path.

Stage29: bionic subject kernel
- Implemented as a unified bionic subject kernel with CLI as the first adapter and synthetic WeChat adapter validation over the same kernel.
- Adds bounded turn capsules with perception, working-field, attention, inhibition, action-market, generation, outcome phases, adapter provenance, operational `bionic_agent_traces`, bionic explainability metrics, trace export, and `accept-stage29` without mutating self-memory or starting WeChat.
- Adds DeepSeek provider compatibility inside the processor fabric; DeepSeek is a replaceable text provider, not a raw runtime call path.

Stage30: unified subject loop
- Implemented as an explicit `subject_loop` contract layered onto the Stage29 bionic capsule.
- Exposes the bounded loop order from perception through state update, with inspectable invariants for action-market-first generation, transport-as-interface, no self-memory mutation, no policy mutation, no second brain, and no new unbounded loop.
- Adds `accept-stage30` without starting WeChat or widening runtime autonomy.

Stage31: debt burn-down and diagnostics
- Implemented adapter registry, controlled state-update gate, subject-loop trace/metrics diagnostics, bionic CLI helper extraction, and `accept-stage31`.
- Keeps all new surfaces offline and operational-only, with no live transport start and no self-memory, policy, or Mind Graph writes from the subject-loop path.

Stage32: response shaping and template pressure
- Implemented bounded deterministic fallback response shaping for the offline bionic kernel.
- Replaces the fixed fallback phrase with query/action/continuity/situational context, exposes `shape` and `context_refs`, and adds `context_shaping_score`.
- Keeps the change offline, processor-fabric-safe, and self-memory-neutral.

Stage33: provider API contracts
- Implemented explicit provider contract diagnostics and `accept-stage33`.
- Corrects `openai_compatible` to use chat-completions while keeping the first-party `responses` provider on the Responses API.
- Keeps provider/API compatibility inside the processor fabric and provider classes.

Stage34: debt registry and visual readiness
- Implemented a classified technical-debt registry and `accept-stage34`.
- Adds `show-debt-registry` so weak spots cannot remain hidden in prose-only handoff notes.
- Adds `show-visual-provider-readiness` so image-task routing is visible, text-only providers reject image requests, and real visual-provider hardening is treated as explicit configured-provider soak debt.

Stage35: internal runtime readiness
- Implemented a machine-checkable internal startup gate for the DeepSeek-backed CLI/API runtime.
- Adds `show-internal-runtime-readiness` and `accept-stage35` to verify DeepSeek primary lanes, redacted env-key presence, local config secret hygiene, and no-WeChat transport quiescence.
- Keeps Stage35 acceptance offline with respect to model calls and live transport; it does not start WeChat, mutate self-memory, or widen autonomy.

Stage36: autonomous inquiry quality
- Implemented an offline bionic-kernel gate for grounded autonomous inquiry quality.
- Removes deterministic label-template inquiry output, caps fallback inquiry to at most one grounded question, and exposes `inquiry_quality_score`, `formatting_pressure_score`, and `question_count`.
- Keeps action-market-first generation, transport-as-interface, no self-memory mutation, and no new planner or loop.

Stage37: bionic self-eval and capability honesty
- Implemented an internal bionic self-dialogue repair gate.
- Adds same-thread bionic trace continuity, provider-backed capability-honesty guards, question/markdown output bounds, and CLI speech fallback when self-eval would otherwise select a non-executable internal action.
- Keeps real image understanding deferred to a configured image-capable provider; Stage37 prevents overclaiming but does not pretend text-only providers can read images.

Stage38: visual provider bridge
- Implemented explicit bionic CLI image input through `agent-run --image-path`.
- Routes raw image understanding through the processor fabric `image_understand` task and stores image-capable provider metadata with visual memory.
- Lets bionic text generation consume visual-memory summaries while keeping DeepSeek and other text-only providers honest about not directly reading raw image pixels.

Stage39: bionic Turing benchmark
- Implemented an internal CLI bionic Turing scorecard for continuity reference, mechanism-leakage prevention, naturalness, question bounds, context grounding, and non-empty speech.
- Adds `show-bionic-turing-scorecard`, `accept-stage39`, and `bionic_turing_score` metrics without live transport, self-memory mutation, or a second decision layer.
- Tightens deterministic fallback and provider prompts so ordinary replies avoid harness phrasing, internal machinery labels, repeated continuity prefixes, and theatrical metaphor pressure.

Stage40: bionic brain OS harness
- Implemented a bounded CLI/API agent harness over the Stage29 bionic kernel with perception, working field, context compiler, deliberation, action-market gating, tool loop, verification, and consolidation intent.
- Adds operational-only `context_bundles`, `bionic_brain_runs`, `bionic_brain_steps`, and `agent_eval_runs` plus `brain-run`, `brain-trace`, `show-context-bundle`, `show-brain-metrics`, `run-agent-eval`, and `accept-stage40`.
- Adds DeepSeek V4 Flash/Pro harness profiles and context-budget metadata while keeping model calls inside the processor fabric, WeChat offline, self-memory unchanged, and repo/runtime writes denied by default.

Stage41: complete engineering agent
- Implemented a controlled CLI/API engineering agent loop over the Stage40 context compiler and processor-fabric deliberation.
- Adds `engineering-run`, `engineering-trace`, `show-engineering-agent-metrics`, and `accept-stage41`.
- Supports bounded read/search/status/test/write tool actions through action-market mutation gates; repo writes require explicit operator authority and private/runtime paths remain blocked.

Stage42: bionic user-simulation performance
- Implemented an isolated first-time-user dialogue performance test over the bionic kernel.
- Adds `run-bionic-user-sim`, `show-bionic-user-sim-scorecard`, HTTP mirrors, and `accept-stage42`.
- Scores novice comprehension, continuity, capability honesty, question quality, mechanism leakage, naturalness, repetition, latency, and high-intensity bionic pressure behavior while writing only operational `agent_eval_runs`.
- Exposes observational `bionic_state` in bionic capsules for inspecting bionic-subject structure without adding a second brain or runtime authority.

Stage43: motivational dynamics field
- Implemented a bounded internal motivational field over the bionic kernel.
- Adds top-level `motivational_field`, action-market `motivation_delta` metadata, `motivational_arousal`, `motivational_uncertainty`, `motivational_max_delta`, HTTP mirror `/accept-stage43`, and `accept-stage43`.
- Models arousal, valence, uncertainty, curiosity, attachment pressure, fatigue, identity coherence, unfinished-loop pressure, diffuse attention, attention center, and replay-stable bounded stochasticity without adding a second brain, self-memory writes, transport authority, or a new unbounded loop.

Stage44: latency-preserving recall demotion
- Reduced ordinary reply latency by keeping non-explicit recall pressure off the blocking Windows/history/reconstruction path.
- Preserves full reconstruction for explicit memory/history/origin recall.
- Keeps WSL as the kernel, Windows as transport/history helper, and watcher without decision authority.

Stage45: biomimetic grounding and context scheduling
- Added current-image perceptual honesty repair and explicit reminder speech-act binding.
- Added processor context scheduling with `8k`/`128k`/`1m` window classes, CJK-aware pressure estimation, stable/volatile prompt digests, history trimming, and high-pressure new-session selection.
- Exposes response-cache mode as exact-response diagnostics so cache misses are not mistaken for provider-context reuse.

Stage46: bionic boundary stress and provider substrate diagnostics
- Added a seven-turn high-intensity biomimetic boundary stress suite for affective pressure, symbolic correction, reminder binding, visual honesty, continuity, self-audit, mechanism leakage, cache pressure, and latency.
- Adds `run-bionic-boundary-stress` and `show-bionic-boundary-stress-scorecard`, persisting only operational `agent_eval_runs`.
- Repairs provider fallback model isolation so DeepSeek lanes do not invoke Codex CLI with DeepSeek model names, and marks local DeepSeek status unavailable when the configured API key env var is missing.

Stage47: provider substrate conflict monitor
- Adds `show-provider-substrate-status` plus HTTP `/provider-substrate-status` for active-provider, lane-primary, fallback, and provider/model mismatch conflicts.
- Stage46 scorecards now include `provider_substrate_score` and `provider_substrate_conflict`, so provider/key/model failures downgrade a run before it is treated as biomimetic evidence.
- DeepSeek key lookup now accepts Windows user/machine environment registry fallback when the current process did not inherit `DEEPSEEK_API_KEY`, and exposes only the redacted `api_key_source`.
- Live DeepSeek Stage46 calibration now preserves turn-level provider/model/usage metadata and fails self-audit when the verbal report contradicts or fails to confirm a real bound reminder commitment.
- Keeps the signal diagnostic-only inside the processor fabric; no WeChat transport, watcher authority, self-memory mutation, or second decision layer is added.

Stage48: biomimetic memory scheduler
- Adds a scheduler that separates working memory, hippocampal indices, cortical schemas, salience gates, and diagnostic consolidation targets over the existing memory fabric.
- Renders stable cortical schema into the provider-cache prefix while keeping working memory and hippocampal indices in dynamic prompt context.
- Exposes memory schedule mode, stable/dynamic token counts, dynamic pressure, salience score, and recall budget in context scheduling and Stage46 debug evidence.
- Does not add a new memory store, start WeChat transport, write self-memory, or move decision authority out of the WSL subject runtime.

Stage49: memory prompt diet and reconstruction priority
- Makes the Stage48 scheduler replace duplicate legacy volatile prompt blocks instead of adding alongside them.
- Drops empty scheduler slots and keeps voice/reply-style constraints in stable cortical schema when legacy blocks are suppressed.
- Promotes recall reconstruction summaries and anchors ahead of generic activation metadata inside the hippocampal budget, preserving continuity under prompt diet.
- Verified with a failing DeepSeek live intermediate run and a passing follow-up run; no self-memory writes, transport widening, new store, or second decision layer.

Stage50: dynamic compression audit
- Adds scheduler-owned `prompt_dynamic_lines` plus `dynamic_compression_audit` so memory compression is inspectable and regression-testable.
- Prioritizes current-state working-memory facts over route/tier metadata under low-salience budgets.
- Exposes compression mode, dropped dynamic line count, compression ratio, and protected-line drop status in context scheduling and Stage46 debug evidence.
- Keeps all changes diagnostic/prompt-scheduling only: no self-memory writes, new store, transport widening, or second decision layer.

Stage51: bionic memory lifecycle and consciousness flow
- Adds a diagnostic biological-memory lifecycle over the Stage50 scheduler: consolidation intent, hippocampal reactivation plan, synaptic-pruning style forgetting gate, and memory pressure.
- Adds a prompt-only consciousness-flow layer ordered by sensory edge, affective tone, memory reactivation, goal pressure, response intention, and uncertainty monitor.
- Exposes lifecycle/flow modes and token counts in context scheduling plus compact Stage46 evidence for consolidation priority, replay guard, and leakage guard.
- Keeps `self_memory_write=false`, `background_loop_allowed=false`, `dream_replay_allowed=false`, and `user_visible=false`; no new store, transport widening, watcher authority, or second decision layer.

Stage52: scheduler-owned prompt fusion
- Fuses Stage51 lifecycle and consciousness-flow prompt material into the existing scheduler-owned dynamic memory budget.
- Renders a single `Bionic Dynamic Frame` when fusion is active, while preserving lifecycle/flow packet and debug evidence.
- Exposes fusion mode, saved line count, Stage51-equivalent dynamic token estimates, and saved token estimates in context scheduling and Stage46 evidence.
- Keeps all changes prompt-scheduling/diagnostic only; no self-memory write, new store, transport widening, watcher authority, or second decision layer.

Stage53: upstream MCP tool substrate
- Implements Holo as an upstream MCP client, not a downstream Holo server.
- Loads reviewed stdio MCP servers from `[mcp_servers.<name>]`, namespaces tools as `server.tool`, and filters discovery/calls through `allowed_tools`.
- Adds CLI diagnostics and Stage41 engineering-agent tools for `mcp_list_tools`, `mcp_call_tool`, and `mcp_read_resource` as `external_observation`.
- Keeps MCP results as observations only; no shell execution through MCP, transport authority, watcher authority, self-memory write, policy mutation, or unbounded loop is added.

## Next Program Arc (Planned)

This planned arc starts after Stage43. The durable execution sources of truth remain `.agent/PLANS.md` and `.agent/STAGE23_27_PROGRAM.md` until a Stage44+ program replaces them.

Provider/API compatibility breadth
- Partially implemented through Stage29 DeepSeek text support, Stage31 adapter registry, Stage33 provider contract diagnostics, Stage34 visual-readiness gating, Stage38 visual-provider bridging, and the post-Stage39 QueueStore-backed provider-response cache for stateless text API calls.
- Future work should broaden API/provider compatibility through the processor fabric, not by adding raw hot-path provider calls.
- Live visual-provider and provider-latency soak should be done before WeChat or live transport is restarted; Stage38 proves the internal CLI image bridge and provider metadata path, while the post-Stage39 cache repair makes exact repeated provider prompts inspectably cheap.

Bionic workflow hardening
- Partially implemented through Stage30 subject-loop invariants, Stage31 subject-loop diagnostics, Stage32 response shaping, Stage34 debt classification, Stage35 internal readiness, Stage36 inquiry-quality gating, Stage37 bionic self-eval/capability-honesty gating, Stage38 visual-provider grounding, Stage39 bionic Turing scoring, Stage40 brain-harness traces/evals, Stage41 controlled engineering-agent traces, Stage42 user simulation, and Stage43 motivational dynamics.
- Future work should improve real-world inquiry quality only through bounded kernel evidence and acceptance gates, without adding a second brain.

Online long-horizon canary
- Deferred until after a new explicit re-plan approves any live widening.
- Any future rollout must stay host-side, shadow-first, whitelist-bound, rate-limited, rollback-safe, replay-disciplined, and action-market-first.

Artifact/tool/outcome progress coupling
- Deferred. This older Stage25 placeholder was explicitly superseded by the dense continuity scheduler milestone and should not be silently folded into Stage28 or any post-Stage28 canary work.

Bounded subject programs
- Deferred. This is no longer the live Stage24 or Stage25 scope and should not be treated as implemented or active-planning default without an explicit re-plan.

## Parked Hypotheses
- broader multi-agent social world
- deeper imagination beyond current recall

## Deferred Experiments
- open-ended world modeling
- explicit multi-step planning
- richer subjective report layer

## Constitutional Constraints
- owner shutdown remains final
- no self-escalation around secrets, auth, or policy
- live repo code is not hot-edited by runtime state loops
- policy boundaries stay hard
- public repos never carry live memory/runtime state
- public repos never carry private subject-profile files; only `.example` templates are tracked
- no second brain layer
- no new unbounded always-on loop
- memory is the self
- processor is replaceable compute
- transport is eyes and hands
- action-market-first deliberation remains the decision path
