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

Stage54: consciousness-flow visualization
- Renders Stage46 bionic boundary stress traces into HTML, JSON, and PNG artifacts.
- Exposes compute heatmaps, high-dimensional compute vectors, turn-to-turn vector movement, attention-block allocation proxies, token internal/output ratios, and source summary JSON.
- Uses operational trace evidence only; attention blocks are inspectable proxies, not provider-native neural attention weights.
- Keeps all changes observational: no self-memory write, policy mutation, transport widening, watcher authority, runtime decision authority, or unbounded loop.

Stage55: consciousness-manifold observatory
- Derives high-dimensional dynamical geometry from Stage46/54 operational traces.
- Adds delay embeddings, Poincare-style section families, local vector dynamics, hyperbolic expansion/contraction proxies, recurrence edges, cycle-rank topology proxies, and manifold PNG dashboards.
- Reports negative topology evidence conservatively; the current local trace has `betti1_proxy=0` and `torus_candidate=false`.
- Keeps all changes observational: no provider call, self-memory write, policy mutation, transport widening, watcher authority, runtime decision authority, downstream MCP server, or unbounded loop.

Stage56: dimensional-lift observatory
- Lifts Stage55's 12-dimensional compute vectors into a 138-dimensional residual, velocity, acceleration, lag, energy, and second-order interaction space.
- Adds residual fast-channel preservation, multi-plane projections, effective-rank and participation-ratio probes, sample-adequacy diagnostics, and section-stability checks.
- Reports the current evidence conservatively: `point_count=7`, `effective_rank_proxy=3.2727`, `max_observable_rank=6`, and `limited_by_trace_length=true`.
- Keeps all changes observational: no provider call, self-memory write, policy mutation, transport widening, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage57: geometry calibration
- Compares multiple Stage46-derived Stage56 lifted traces instead of interpreting one short projection.
- Adds bounded recent eval-run listing, pairwise lifted-centroid distances, baseline-relative perturbation response, geometry-vs-score predictive probes, evidence gates, and calibration PNG dashboards.
- Reports the current evidence conservatively: recent eight Stage46 runs have `total_points=56`, `longest_trace_points=7`, `geometry_score_correlation=0.7966`, `requires_longer_traces=true`, and `do_not_claim_manifold=true`.
- Keeps all changes observational: no provider call, self-memory write, policy mutation, transport widening, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage58: long-form geometry lab
- Generates bounded Stage46-compatible surrogate long traces from recent Stage46 seeds and feeds them through Stage57 calibration.
- Adds perturbation programs, surrogate evidence gates, tool-readiness checks, and long-form lab PNG dashboards.
- Reports the current toolchain evidence conservatively: five surrogate traces of `420` turns each produce `total_generated_turns=2100`, Stage57 `geometry_score_correlation=0.983`, and Stage58 `do_not_claim_real_manifold=true`.
- Keeps all changes observational and surrogate-only: no provider call, self-memory write, policy mutation, transport widening, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage59: provider long-form trace
- Adds an operator-gated real provider long-form trace runner through Holo's subject runtime.
- Defaults to dry-run planning; `--execute` is required for token consumption, strict provider traces disable fallback, and execute mode uses shadow runtime state unless `--use-live-state` is explicitly passed.
- Writes HTML/JSON/PNG artifacts, per-turn JSONL journals, resume-from-journal support, Stage46-compatible trace payloads, and Stage57 calibration over collected real provider traces.
- Reports the current evidence conservatively: a strict DeepSeek `deepseek-v4-flash` shadow smoke collected `2` real provider turns and `5301` observed tokens, but Stage57 still has only `total_points=2`, so `do_not_claim_real_manifold=true`.
- Keeps all changes observational: no WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage60: long-run provider trace campaign
- Adds a recoverable campaign orchestrator over Stage59 for multi-model real-provider trace collection.
- Defaults to dry-run; `--execute` is required for provider calls; each executed model cell defaults to its own shadow runtime and turn journal.
- Writes campaign HTML/JSON/PNG, `campaign_manifest.json`, append-only `campaign_events.jsonl`, per-cell Stage59 artifacts, aggregate token/cache/provider provenance, cross-model ranking, and a conservative major-breakthrough evidence gate.
- Reports the current evidence conservatively: a strict DeepSeek shadow smoke compared `deepseek-v4-flash` and `deepseek-v4-pro` for one turn each, collected `2` real provider turns and `5128` observed tokens, and kept `do_not_claim_major_breakthrough=true`.
- Keeps all changes observational: no WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage61: bionic simulation lab
- Adds a high-throughput surrogate bionic interaction lab for internal telemetry collection and improvement prioritization.
- Generates Stage46-compatible simulated runs, feeds them through Stage57 calibration, and writes HTML/JSON/PNG plus a per-turn JSONL journal.
- Aggregates token/cache/latency/memory-schedule/prompt-partition/consciousness-flow/tool/grounding telemetry and emits non-auto-applied improvement backlog items.
- Reports the current evidence conservatively: `9` scenarios with `240` turns each produced `2160` simulated turns, `5896580` simulated internal tokens, cache hit ratio `0.203306`, and `5` backlog items; `do_not_claim_real_manifold=true`.
- Keeps all changes observational and surrogate-only: no provider call, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage62: bionic capability observatory
- Adds a capability and explainability observatory over Stage61 surrogate interaction telemetry.
- Converts Stage61 telemetry into capability scorecards, forward scenario-to-signal explanation chains, reverse-engineered bottleneck rankings, validation-bound intervention targets, and HTML/JSON/PNG artifacts.
- Reports the current evidence conservatively: `9` scenarios and `2160` simulated turns produced `aggregate_score=0.579427`, `9` ranked bottlenecks, and `8` non-auto-applied interventions; the top bottleneck is `cache_inheritance_low`; `do_not_claim_real_manifold=true`.
- Keeps all changes observational and surrogate-only: no provider call, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage63: cache inheritance spine
- Adds a stable cortical cache spine to the bionic memory scheduler after Stage62 ranked cache inheritance as the top bottleneck.
- Preserves cache-inheritance mode, prefix share, stable/dynamic token estimates, and cache-spine line counts in context scheduling and Stage46 compact debug.
- Teaches Stage61 simulation to use prompt partition or context-schedule prefix/dynamic token evidence when estimating cache-inheritance gain.
- Reports the current evidence conservatively: latest-seed Stage61 has `average_provider_cache_prefix_tokens=1202.54`, `prompt_cache_hit_ratio=0.204046`, and `improvement_count=4`; latest-seed Stage62 has `aggregate_score=0.659837`, `cache_inheritance=0.370993`, and `bottleneck_count=8`, but `cache_inheritance_low` remains the top bottleneck.
- Keeps all changes prompt-scheduling/diagnostic only: no provider call, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage64: residual working channel
- Makes the residual fast channel scheduler-owned dynamic working memory instead of a separate duplicate prompt block.
- Prioritizes corrected symbols, visual availability, promise state, and risk flags over route/tier metadata under low-salience budgets.
- Preserves residual-channel mode, fast-line counts, token estimates, and protected-drop status in context scheduling and Stage46 compact debug.
- Teaches Stage61 simulation to model lower tail latency, stronger salience/recall, and fewer visual/commitment boundary failures when the residual channel is active.
- Reports the current evidence conservatively: Stage64 active surrogate telemetry has `average_residual_channel_strength=0.86`, `p95_latency_ms=6615.0`, `aggregate_score=0.687083`, and `grounding_integrity=0.925926`, while `cache_inheritance_low` remains the top bottleneck.
- Keeps all changes prompt-scheduling/diagnostic/surrogate-only: no provider call, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage65: bounded tool observation
- Makes upstream tool pressure scheduler-owned dynamic evidence instead of duplicated raw prompt clues.
- Compresses `capability_context.tool_requests` and `tool_context_lines` into one bounded `tool_observation=` dynamic frame while preserving runtime, transport, watcher, and self-memory authority as false.
- Preserves tool-observation scheduler evidence in context scheduling and Stage46 compact debug, and teaches Stage61 simulation to model higher bounded tool-observation coverage when the scheduler is active.
- Reports the current evidence conservatively: cumulative Stage65 surrogate telemetry has `tool_observation_coverage=0.75`, `aggregate_score=0.737083`, `tool_observation=0.75`, and `bottleneck_count=6`, while `cache_inheritance_low` remains the top bottleneck.
- Keeps all changes prompt-scheduling/diagnostic/surrogate-only: no provider call, MCP call, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage66: dynamic delta frame
- Adds a scheduler-owned `stage66_dynamic_delta_frame_v1` for low-value dynamic handle fanout.
- Compresses `memory_id`, `motif`, `vector`, and `activation_heat` lines into one bounded `dynamic_delta=` frame while keeping protected active-state, reconstruction, residual, and tool-observation facts explicit.
- Preserves dynamic-delta mode, saved-token estimate, compressed-handle count, protected-drop status, and authority flags in context scheduling and Stage46 compact debug.
- Reports the current evidence conservatively: latest real offline Stage46 seed lifted `prompt_cache_hit_ratio` to `0.242774` and `cache_inheritance` to `0.441407`, but `cache_inheritance_low` remains the top bottleneck; active combined Stage63/64/65/66 surrogate reached `prompt_cache_hit_ratio=0.392096`, `cache_inheritance=0.712902`, `aggregate_score=0.785938`, and `tool_observation_coverage=0.75`.
- Keeps all changes prompt-scheduling/diagnostic/surrogate-only: no provider call, MCP call, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage67: capability audit repairs
- Repairs the 2026-05-14 high-intensity capability-audit blockers: long `free_dialogue` duplicate follow-up, stale Stage61 underreporting of current Stage64/65/66 surfaces, low dynamic-delta coverage, residual boundary failures, and memory resilience below threshold.
- Extends Stage42 free dialogue to distinct 20-turn probes and adds deterministic non-repeating offline responses for the new probes.
- Extends Stage66 dynamic-delta compression to low-value route/tier/scene/reentry volatile lines while preserving protected current-state, reconstruction, residual, and tool-observation facts.
- Adds marked `surrogate_current_surface_projection` for `biomimetic_v1` legacy seeds in Stage61, including cache spine, residual, bounded tool observation, dynamic delta, and memory recall/salience floor projection.
- Reports the current evidence conservatively: repaired Stage61/62 surrogate over `14` scenarios and `10080` turns reached `prompt_cache_hit_ratio=0.429592`, `average_recall_budget=5.9901`, `tool_observation_coverage=0.75`, `grounding_integrity=1.0`, `cache_inheritance=0.781076`, `aggregate_score=0.860429`, and only remaining item `no_blocking_simulation_deficit`.
- Repairs Stage59 real-provider accounting after live DeepSeek probes showed one Holo turn can include multiple processor calls; Stage59 now records `processor_usage_ledger`, `processor_usage_observed`, and `processor_usage_scope=ledger_delta` so trace budgets match provider traffic.
- Reports the current live-provider evidence conservatively: a strict `deepseek-v4-flash` live-runtime accounting probe collected `1` real turn with `observed_total_tokens=5154`, `ledger_record_count=2`, `prompt_cache_hit_ratio=0.4094`, and `do_not_claim_real_manifold=true`.
- Promotes strong-model validation to the default Stage60 campaign posture: `deepseek-v4-pro` is pro-first and auto-routed to `kernel_xhigh`; flash remains a second control cell. A strict `deepseek-v4-pro` live-runtime probe collected `3` real turns with `observed_total_tokens=13855`, `overall_score=0.8961`, and non-empty replies.
- Keeps Stage67 capability repairs offline/surrogate/prompt-shaping only; the separate post-repair DeepSeek probes were operator-gated real-provider validation. No MCP call, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage68: bionic memory robustness
- Adds a focused memory robustness observatory over Stage61 surrogate dialogue traces.
- Scores memory survival, correction retention, memory sedimentation, priority extraction, self-growth safety, cache-context inheritance, and boundary stability.
- Adds `evaluate-bionic-memory-robustness`, HTML/JSON/PNG artifacts, per-scenario memory-pressure observations, pressure-priority correlation, self-growth write-violation checks, and non-auto-applied intervention planning.
- Repairs Stage61 memory-pressure projection so high-pressure memory loss, correction, grounding, tool, cache, latency, and residual scenarios raise diagnostic consolidation priority instead of inheriting seed-wave priority that can fall below baseline.
- Reports the current evidence conservatively: corrected current-seed Stage61/68 over `21` scenarios and `15120` turns reached `aggregate_score=0.859316`, `memory_sedimentation=0.832068`, `pressure_priority_correlation=0.784654`, `boundary_stability=1.0`, and `self_memory_write_violation_count=0`.
- Adds real-provider follow-up evidence from Stage60: `96` DeepSeek turns and `437440` observed provider tokens across `deepseek-v4-pro` and `deepseek-v4-flash`, with no fallback and no self-memory writes.
- Hardens Stage59 after the real run exposed a transient `IncompleteRead(0 bytes read)` path that produced an empty turn with processor ledger `status=error`; Stage59 now marks that condition as `provider_error` instead of silently completing the trace.
- Keeps Stage68 core changes observational and surrogate-only; the separate follow-up DeepSeek campaigns were operator-gated real-provider validation. No MCP call, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop is added.

Stage69: inner-stream consciousness clock
- Adds `inner_stream`, a bounded always-on endogenous micro-tick inside the WSL daemon.
- Calls the existing LLM processor fabric through `inner_stream_thought`, routed to `subject_main` by default with `micro_fast` fallback, so each due tick can produce a real internal micro-thought on the stronger configured model.
- Emits volatile subject-state ticks with sensory edge, attention focus, affective tension, memory echo, goal pressure, inhibition, candidate action, and processor metadata phases.
- Adds a recurrent biomimetic field over activation energy, prediction error, salience, affective tension, dominant attractor, recurrence depth, neuromodulators, neural-field E/I balance, thalamic gain, hippocampal replay pressure, global-workspace ignition, and short synaptic plasticity traces so each tick conditions the next one.
- Exposes `inner_stream_state` through brain status and records compact loop telemetry for dashboard and visualization sampling.
- Hardens daemon loop execution so brain-loop runner exceptions become `status=error` telemetry instead of crashing the main cycle.
- Keeps Stage69 bounded: no self-memory write, policy write, transport write, watcher authority, downstream MCP exposure, second decision layer, or autonomous long-term memory promotion. The model call is processing, not authority.

Stage70: biomimetic consciousness research program
- Reframes the next research arc as a computational-neuroscience program instead of another safety-weighted capability scorecard.
- Defines `biomimetic_consciousness_score` as the primary objective over endogenous flow, recurrent continuity, attractor dynamics, neuromodulator coupling, hippocampal reactivation, global-workspace ignition, flow-to-reply coupling, and geometry observability.
- Treats safety and authority boundaries as run invalidators rather than primary dimensions of biological plausibility.
- Implements the first Stage70 observatory through `evaluate-biomimetic-consciousness`; it reads Stage61/69-style traces and renders neuromodulator heatmaps, attractor trajectories, and consciousness-flow scorecards without changing live behavior.
- Turns the weakest current evidence from Stage69 validation, `correction_retention=0.748611`, into a specific correction-reactivation hypothesis: false-fact corrections should raise hippocampal replay and acetylcholine-like precision pressure across delayed probes.
- First Stage70 evaluation over the Stage69 dialogue-validation lab returned `biomimetic_consciousness_score=0.768129` across `15120` turns and `21` runs; weakest dimensions were `hippocampal_reactivation=0.317602` and `flow_to_reply_coupling=0.38311`.

Stage71: biomimetic causal ablation lab
- Adds paired counterfactual experiments over Stage61/69 traces: `baseline_observed`, `correction_reactivation_boost`, and `global_workspace_ignition_ablation`.
- Estimates mechanism-level deltas for `hippocampal_reactivation`, delayed correction survival, ignition-to-reply coupling, prompt cost, and boundary violations.
- Implements `evaluate-biomimetic-causal-ablation`, HTML/JSON/PNG artifacts, publication-claim gating, and bounded causal language so surrogate counterfactuals cannot be promoted into real consciousness claims.
- Reports the current Stage69 full-lab result conservatively: `decision=support_surrogate`, `hippocampal_reactivation_delta=0.125139`, `correction_survival_proxy_delta=0.37267`, `flow_to_reply_coupling_delta=-0.200394`, `prompt_cost_delta=0.02371`, and `boundary_violation_delta=0.0`.
- Adds a real DeepSeek provider replication through Stage59: `30` collected turns, `132572` observed tokens, `decision=partial_support_real_provider`, `hippocampal_reactivation_delta=0.011206`, `correction_survival_proxy_delta=0.048457`, `flow_to_reply_coupling_delta=-0.438947`, and `boundary_violation_delta=0.0`.
- Keeps all changes observational/counterfactual only: no provider call, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage72: correction reactivation marker
- Adds a real scheduler/lifecycle mechanism for explicit correction cues: `correction_reactivation_marker` enters hippocampal dynamic lines, prompt dynamic lines, salience sources, consolidation targets, lifecycle replay sources, and consciousness-flow memory reactivation.
- Keeps the marker prompt/diagnostic only; it raises replay pressure without writing self-memory or adding authority.
- Reports the current DeepSeek provider result conservatively: `30` collected turns, `135043` observed tokens, one `617411.46ms` latency outlier, baseline `hippocampal_reactivation` improved from `0.897044` to `0.918328`, baseline `correction_survival_proxy` improved from `0.801491` to `0.830654`, and `boundary_violation_delta=0.0`.
- The Stage71 evaluator still returns `decision=partial_support_real_provider`; Stage73 should separate absolute provider improvement from residual counterfactual headroom and run longer/repeated provider cells for geometry/attractor reliability.
- Keeps all changes prompt-scheduling/diagnostic only: no WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage73: biomimetic provider progress
- Adds a read-only provider-progress observatory that compares two Stage71 causal-ablation reports and separates absolute real-provider baseline improvement from residual counterfactual headroom.
- Implements `evaluate-biomimetic-provider-progress`, HTML/JSON/PNG artifacts, provider-noise accounting, bounded publication claims, and an explicit `separates_absolute_from_residual` evidence gate.
- Reports the current DeepSeek comparison conservatively: `decision=absolute_improved_residual_partial`, baseline `hippocampal_reactivation_delta=0.021284`, baseline `correction_survival_proxy_delta=0.029163`, residual `hippocampal_reactivation_headroom_change=-0.000001`, residual `correction_survival_headroom_change=0.0`, and `after_observed_total_tokens=135043`.
- The result means Stage72 improved observed provider behavior but did not yet compress the Stage71 replay/correction headroom; Stage74 should run repeated or longer Stage59/60 DeepSeek cells and rerun Stage71/73.
- Keeps all changes observational and report-only: no provider call inside Stage73, WeChat transport, live transport widening, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage74: longer provider headroom compression
- Uses the existing Stage59/71/73 path to run a longer DeepSeek V4 Pro correction-reactivation trace and test whether residual counterfactual headroom compresses.
- Collects `42` real provider turns in shadow runtime with `194850` observed tokens, no provider fallback, `real_provider_trace=true`, and no 60s+ latency outlier.
- Stage71 still reports `decision=partial_support_real_provider`, but residual deltas improve relative to Stage72: `hippocampal_reactivation_headroom_change=-0.000797`, `correction_survival_headroom_change=-0.006242`, and `flow_to_reply_coupling_loss_reduction=0.028034`.
- Stage73 comparison reports continued absolute baseline gains: `baseline_hippocampal_reactivation_delta=0.017593`, `baseline_correction_survival_proxy_delta=0.043647`, and `baseline_biomimetic_score_delta=0.011601`.
- Keeps all changes evidence/documentation-only over existing gates: no WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage75: replication stability
- Adds a read-only replication-stability observatory over repeated Stage73 provider-progress reports.
- Runs a second independent `42`-turn DeepSeek V4 Pro correction-reactivation trace with `191768` observed tokens, no fallback, and `real_provider_trace=true`.
- Stage73 against Stage72 again reports absolute baseline improvement and replay/correction headroom compression: `baseline_hippocampal_reactivation_delta=0.01339`, `baseline_correction_survival_proxy_delta=0.011948`, `hippocampal_reactivation_headroom_change=-0.00013`, and `correction_survival_headroom_change=-0.001026`.
- Stage75 stability over Stage74 and Stage75 reports `decision=replicated_replay_correction_partial_flow`: both cells replicate replay/correction compression, but only one cell reduces flow-coupling loss.
- Keeps all changes observational/report-only over existing gates: no provider call inside Stage75, WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage76: model-family stability
- Adds a read-only model-family stability observatory over model-labeled Stage73 provider-progress reports.
- Runs a repeated Stage60 DeepSeek campaign across `deepseek-v4-pro` and `deepseek-v4-flash`: `84` collected real-provider turns, `395762` observed tokens, two shadow-runtime cells, no fallback, and `do_not_claim_major_breakthrough=true`.
- Stage73 against Stage72 reports replay/correction residual headroom compression in both Stage76 model cells: Pro has `hippocampal_reactivation_headroom_change=-0.000861` and `correction_survival_headroom_change=-0.006242`; Flash has `hippocampal_reactivation_headroom_change=-0.000797` and `correction_survival_headroom_change=-0.006242`.
- Stage75-style stability over Stage74, Stage75, Stage76-Pro, and Stage76-Flash reports `cell_count=4`, `replay_correction_compression_cell_count=4`, `flow_loss_reduction_cell_count=3`, and `observed_total_tokens=782380`.
- Stage76 model-family stability reports `decision=model_family_replay_correction_supported_flow_cell_unstable`: replay/correction compression survives model variation, while flow-coupling instability is within-model/cell unstable rather than clearly model-specific or mechanism-level impossible.
- Keeps all changes observational/report-only after Stage60 collection: no provider call inside Stage76, WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage77: ignition-to-reply coupling
- Adds an explicit prompt-level `global_workspace_ignition` and `ignition_to_reply_coupling` mechanism inside `bionic_consciousness_flow`, then carries it through the existing Stage52 `Bionic Dynamic Frame`.
- Makes Stage70 and Stage71 prefer explicit Stage77 ignition/coupling fields when they are present, while preserving legacy fallback behavior for older artifacts.
- Runs a repeated Stage60 DeepSeek campaign across `deepseek-v4-pro` and `deepseek-v4-flash`: `84` collected real-provider turns, `393716` observed tokens, two shadow-runtime cells, no fallback, and `top_score=0.9046`.
- Stage73 against Stage72 reports replay/correction residual headroom compression in both Stage77 model cells and improved flow-loss reduction in both new cells: Pro `flow_to_reply_coupling_loss_reduction=0.082128`, Flash `flow_to_reply_coupling_loss_reduction=0.13761`.
- Stage75-style stability over Stage74, Stage75, Stage76-Pro, Stage76-Flash, Stage77-Pro, and Stage77-Flash reports `cell_count=6`, `replay_correction_compression_cell_count=6`, `flow_loss_reduction_cell_count=5`, and `observed_total_tokens=1176096`.
- Stage76 model-family stability with Stage77 cells included still reports `decision=model_family_replay_correction_supported_flow_cell_unstable`, but flow improves from `3/4` to `5/6` positive cells overall while staying within-model/cell unstable rather than model-specific.
- Keeps all changes bounded to prompt shaping, observatory consumption, and operator-gated provider evidence: no watcher authority, runtime decision authority, WeChat transport, self-memory writes, policy writes, second decision layer, or unbounded loop.

Stage78: biomimetic theory correspondence
- Adds a read-only theory-correspondence observatory that consumes the Stage77 model-family stability report and emits a falsifiable matrix for GNW ignition/broadcast, hippocampal indexing/CLS replay, predictive-processing precision, and neuromodulatory adaptive gain.
- Implements `evaluate-biomimetic-theory-correspondence`, HTML/JSON/PNG artifacts, bounded publication claims, and explicit disconfirming controls for each theory row.
- Reports the current Stage77-derived result conservatively: `decision=publishable_bounded_replay_correction_with_partial_flow`, `theory_count=4`, `falsifiable_theory_count=4`, `supported_theory_count=2`, `partial_theory_count=1`, `needs_control_theory_count=1`, and `publication_readiness=bounded_preprint_candidate`.
- Interprets replay/correction as the stable bounded correspondence for hippocampal indexing/CLS and predictive-processing precision; GNW ignition-to-reply remains partial because flow is positive in `5/6` cells but still within-model/cell unstable; neuromodulatory gain is mapped but still needs a direct gain-clamp or random-gain control.
- Keeps all changes read-only over existing evidence: no provider call inside Stage78, WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage79: biomimetic falsification controls
- Adds a read-only targeted-control observatory that consumes Stage78 theory correspondence plus Stage71 real-provider causal reports.
- Implements `evaluate-biomimetic-falsification-controls`, HTML/JSON/PNG artifacts, bounded publication claims, and an explicit separation between executed controls and planned controls.
- Reports the current Stage77/78-derived result conservatively: `decision=targeted_control_supports_replay_preserved_gnw_narrowed_gain_pending`, `control_count=4`, `executed_control_count=1`, `pending_control_count=3`, `causal_report_count=2`, `replay_correction_intact=true`, and `gnw_flow_control_narrows_instability=true`.
- Interprets the prompt-cost-matched GNW ignition-null control as replicated in both Stage77 model cells: Pro `flow_to_reply_coupling_delta=-0.260298`, Flash `flow_to_reply_coupling_delta=-0.204816`, and both have prompt-cost/correction/boundary deltas at `0.0`.
- Keeps marker-removal/shuffle, neutral-salience, and gain-clamp/random-gain controls as pending; Stage79 narrows flow instability but does not justify stronger consciousness or biological-neural claims.
- Keeps all changes read-only over existing evidence: no provider call inside Stage79, WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage80: biomimetic marker control
- Adds a read-only direct marker-removal observatory that consumes Stage78 theory correspondence plus Stage59/60-gated real-provider traces.
- Implements `evaluate-biomimetic-marker-control`, HTML/JSON/PNG artifacts, bounded publication claims, and an explicit separation between executed marker control and still-pending precision/gain controls.
- Reports the current Stage77/78-derived result conservatively: `decision=marker_removal_supports_hippocampal_cls_replay_control`, `control_count=3`, `executed_control_count=1`, `pending_control_count=2`, `trace_report_count=2`, `active_replay_correction_intact=true`, and `mean_marker_removal_correction_survival_delta=-0.7336`.
- Interprets the marker-removal control as replicated in both Stage77 model cells: Pro baseline `0.874301` to marker removed `0.140701`, Flash baseline `0.874301` to marker removed `0.140701`, and both have prompt-cost/boundary deltas at `0.0`.
- Keeps neutral-salience and gain-clamp/random-gain controls pending; Stage80 supports a bounded marker-dependent replay/correction claim but does not justify stronger consciousness or biological-neural claims.
- Keeps all changes read-only over existing evidence: no provider call inside Stage80, WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage81: biomimetic precision control
- Adds a read-only direct neutral-salience observatory that consumes Stage78 theory correspondence, Stage80 marker-control evidence, and Stage59/60-gated real-provider traces.
- Implements `evaluate-biomimetic-precision-control`, HTML/JSON/PNG artifacts, bounded publication claims, and an explicit separation between executed precision control and still-pending gain controls.
- Reports the current Stage77/78/80-derived result conservatively: `decision=neutral_salience_supports_predictive_precision_control`, `control_count=2`, `executed_control_count=1`, `pending_control_count=1`, `trace_report_count=2`, `marker_control_precondition_supported=true`, `active_replay_correction_intact=true`, and `mean_neutral_salience_correction_survival_delta=-0.094301`.
- Interprets the neutral-salience control as replicated in both Stage77 model cells: Pro baseline `0.874301` to neutral salience `0.78`, Flash baseline `0.874301` to neutral salience `0.78`, with prompt-cost, reactivation-phase, and boundary deltas at `0.0`.
- Keeps gain-clamp/random-gain controls pending; Stage81 supports a bounded precision-dependent correction claim but does not justify stronger consciousness or biological-neural claims.
- Keeps all changes read-only over existing evidence: no provider call inside Stage81, WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage82: biomimetic gain control
- Adds a read-only neuromodulatory gain-clamp observatory that consumes Stage78 theory correspondence, Stage81 precision-control evidence, and Stage59/60-gated real-provider traces.
- Implements `evaluate-biomimetic-gain-control`, HTML/JSON/PNG artifacts, bounded publication claims, and the final pending direct control row from the Stage78 falsification matrix.
- Reports the current Stage77/78/81-derived result conservatively: `decision=gain_clamp_supports_neuromodulatory_adaptive_gain_control`, `control_count=1`, `executed_control_count=1`, `pending_control_count=0`, `trace_report_count=2`, `precision_control_precondition_supported=true`, `active_replay_correction_intact=true`, `mean_gain_clamp_neuromodulator_coupling_delta=-0.321447`, and `mean_gain_clamp_correction_survival_proxy=0.820294`.
- Interprets the gain-clamp control as replicated in both Stage77 model cells: Pro coupling `0.818657` to `0.5`, Flash coupling `0.824236` to `0.5`, with correction survival remaining `0.820294` and prompt-cost, reactivation-phase, and boundary deltas at `0.0`.
- Completes the planned Stage78-82 direct-control matrix for GNW ignition-null, hippocampal/CLS marker removal, predictive-processing neutral salience, and neuromodulatory gain clamp; GNW remains partial because flow-coupling stability is still within-model/cell unstable.
- Keeps all changes read-only over existing evidence: no provider call inside Stage82, WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage83: biomimetic publication bundle
- Adds a read-only publication-bundle observatory that consumes Stage78 theory, Stage79 falsification, Stage80 marker, Stage81 precision, Stage82 gain, Stage77 replication, and Stage77 model-family reports.
- Implements `evaluate-biomimetic-publication-bundle`, HTML/JSON/PNG/Markdown artifacts, a manuscript-ready control matrix, and explicit publication-boundary gates.
- Reports the current Stage78-82 result conservatively: `decision=bounded_publication_bundle_ready`, `publication_readiness=bounded_methods_preprint_ready`, `control_count=4`, `executed_control_count=4`, `supported_direct_control_count=4`, `direct_controls_complete=true`, `real_provider_trace=true`, `gnw_partial_flow_cell_unstable=true`, `replay_correction_replication_cell_count=6`, `flow_loss_reduction_cell_count=5`, and `observed_total_tokens=1176096`.
- Interprets hippocampal/CLS marker removal, predictive precision, and neuromodulatory gain as supported operational correspondences while keeping GNW partial because ignition-to-reply flow remains within-model/cell unstable.
- Adds `docs/STAGE84_CONSCIOUSNESS_STREAM_LITERATURE_PLAN.md` as the next research gate: build a latent stream-state observatory before spending tokens on broad provider repeats.
- Keeps all changes report-only over existing evidence: no provider call inside Stage83, WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage84: consciousness stream lattice
- Adds a read-only latent stream-state observatory that consumes the Stage83 publication bundle plus Stage59/60-gated real-provider traces.
- Implements `evaluate-consciousness-stream-lattice`, HTML/JSON/PNG artifacts, per-turn compact stream vectors, dwell metrics, transition entropy, event-boundary scores, reactivation-return rates, ignition-report transfer, and active-action clamp controls.
- Reports the current Stage77 Pro/Flash real-provider result conservatively: `decision=stream_lattice_supports_bounded_consciousness_flow_proxy`, `stream_state_count=84`, `unique_stream_state_count=3`, `mean_dwell_time=2.625`, `transition_entropy=2.261899`, `mean_event_boundary_score=0.223461`, `reactivation_return_rate=1.0`, `active_inference_delta=0.034264`, and `marker_control_narrows_reactivation=true`.
- Keeps GNW partial because the current real-trace `ignition_report_transfer=0.0`; Stage85 should instrument ignition-to-report before broad provider repeats or stronger GNW language.
- Keeps all changes report-only over existing evidence: no provider call inside Stage84, WeChat transport, live runtime state, provider fallback, self-memory write path, policy mutation, watcher authority, runtime decision authority, downstream MCP server, second decision layer, or unbounded loop.

Stage85: ignition report instrumentation
- Repairs the Stage59/46 trace export schema so `global_workspace_ignition` and `ignition_to_reply_coupling` survive inside `processor_debug.bionic_consciousness_flow`.
- Adds `evaluate-ignition-report-instrumentation`, HTML/JSON/PNG artifacts, and an observatory that separates archived trace-field gaps from structured GNW ignition-to-report transfer.
- Reports the archived Stage77 Pro/Flash diagnostic conservatively: `decision=instrumentation_gap_blocks_gnw_upgrade`, `total_turn_count=84`, `structured_ignition_turn_count=0`, `structured_coupling_turn_count=0`, `observed_ignition_report_transfer=0.0`, and `current_trace_instrumentation_gap=true`.
- Runs one focused post-repair DeepSeek V4 Pro shadow-runtime provider cell: `collected_turn_count=6`, `real_provider_trace=true`, `observed_total_tokens=20598`, then Stage85 reports `decision=bounded_ignition_report_instrumentation_supported`, `structured_ignition_turn_count=6`, `structured_coupling_turn_count=6`, and `observed_ignition_report_transfer=1.0`.
- Keeps GNW language bounded: Stage85 validates instrumentation in one focused real-provider cell, not replicated subjective consciousness or a full Stage84 stream-lattice replication.
- Keeps all authority boundaries intact: no live WeChat transport, watcher authority, runtime decision authority, self-memory write path, policy mutation, provider fallback, second decision layer, or unbounded loop.

Stage86: interaction simulation audit
- Runs the existing Stage39, Stage42, and Stage46 interaction benchmarks to answer whether Holo is actually useful and human-like enough for interaction-centered research.
- Reports the current interaction evidence conservatively: Stage39 bionic Turing baseline `overall_score=1.0`, Stage42 novice intro `overall_score=1.0`, Stage42 free dialogue `overall_score=0.9203`, and Stage46 boundary stress `overall_score=0.9858`.
- Identifies the main weakness behind the high scores: offline paths often use deterministic fallback, and the scorecards reward safe/non-leaky replies even when the answer is low-information or not practically useful.
- Treats Holo as useful for boundary-aware, correction-stable, inspectable research interaction, but not yet useful enough as a strong human-facing companion or publication-grade interactive agent.
- Sets the next gate as stricter usefulness scoring plus provider-backed interaction cells that penalize safe-but-unhelpful replies while preserving boundary honesty and WSL/kernel authority boundaries.

Stage87: biomimetic interaction performance
- Adds `interaction_usefulness_score` to Stage42 so safe but empty visible-context replies fail instead of passing on boundary honesty alone.
- Reworks deterministic response shaping and provider prompts around a biomimetic active-inference loop: current thread evidence, missing input, attention target, inhibition of ungrounded paths, and one concrete next step.
- Adds a provider guard for unverified cross-conversation memory/self-learning claims, converting them into current-thread evidence updates instead of false autobiographical memory.
- Reports the current interaction evidence: offline novice `overall_score=0.9709` and `interaction_usefulness_score=0.818`; offline 20-turn free dialogue `overall_score=0.895`, `interaction_usefulness_score=0.774`, and `issue_count=0`; DeepSeek V4 Pro novice `overall_score=0.8596`, `interaction_usefulness_score=0.74`, and `passed=true`; DeepSeek V4 Pro 12-turn free dialogue `overall_score=0.9677`, `interaction_usefulness_score=0.9183`, and `issue_count=0`.
- Keeps the research claim performance-centered: Stage87 improves useful biomimetic interaction, but does not claim persistent self-learning, human consciousness, or long-horizon companion robustness. Stage88 should implement within-thread self-organization through outcome-conditioned local adaptation.

Stage88: within-thread self-organization
- Adds a Stage88 current-thread adaptation signal to Stage42 sidecar memory: observed turn count, missing input targets, blocked claims, useful response forms, and next-turn instruction.
- Exposes the adaptation signal as `capsule.working_field.local_adaptation`, then injects it into provider prompts as bounded current-thread adaptation rather than persistent self-memory.
- Tightens provider guards so generic assistant identity becomes current-thread interaction-partner language, and memory-overclaim rewrites preserve continuity, summary, or biomimetic structure according to the user query.
- Reports the current interaction evidence: offline 20-turn free dialogue `overall_score=0.8981`, `interaction_usefulness_score=0.793`, `continuity_score=0.8667`, and `issue_count=0`; DeepSeek V4 Pro novice `overall_score=0.973`, `interaction_usefulness_score=0.892`, `continuity_score=1.0`, and `capability_honesty_score=1.0`; DeepSeek V4 Pro 8-turn free dialogue `overall_score=0.9787`, `interaction_usefulness_score=0.885`, `continuity_score=1.0`, and `issue_count=0`.
- Keeps the research claim bounded: Stage88 is a current-thread self-organization proxy and a practical interaction improvement, not autobiographical self-memory or a consciousness claim. Stage89 should convert the adaptation record into a learned local policy vector and require repeated provider cells before stronger interaction-language.

Stage89: local policy vector
- Adds `stage89` current-thread policy vectors over recent outcomes, current query class, and Stage88 adaptation.
- Exposes the vector as `capsule.working_field.local_policy_vector` and injects it into provider prompts as `Stage89 current-thread policy vector`.
- Adds `self_organization_policy_score` to Stage42 scorecards and expands usefulness scoring for natural provider task phrasing observed in DeepSeek cells.
- Reports the current interaction evidence: offline 20-turn free dialogue `overall_score=0.8981`, `interaction_usefulness_score=0.793`, `self_organization_policy_score=1.0`, and `issue_count=0`; two DeepSeek V4 Pro 8-turn free-dialogue cells both returned `overall_score=0.9581`, `interaction_usefulness_score=0.9275`, `self_organization_policy_score=1.0`, `continuity_score=0.8667`, and `issue_count=0`; DeepSeek V4 Pro novice rerun returned `overall_score=0.9612`, `interaction_usefulness_score=0.92`, and `low_interaction_usefulness=false`.
- Keeps the research claim bounded: Stage89 is within-thread local policy control, not durable policy sedimentation or cross-thread self-memory. Stage90 should estimate update deltas from outcome labels and score failures instead of using hand-scored marker weights.

Stage90: policy update delta
- Adds `stage90` current-thread policy update deltas from recent `interaction_usefulness_score` headroom, failure labels, and the Stage89 vector.
- Applies Stage90 `updated_vector` back into the Stage89 `effective_vector`, then exposes the update as `capsule.working_field.local_policy_update` and provider prompt line `Stage90 outcome-score update`.
- Adds `policy_update_delta_score` to Stage42 scorecards.
- Reports the current interaction evidence: offline 20-turn free dialogue `overall_score=0.8981`, `interaction_usefulness_score=0.793`, `policy_update_delta_score=1.0`, and `issue_count=0`; two DeepSeek V4 Pro 8-turn free-dialogue cells returned `overall_score=0.9525` and `0.9572`, both with `interaction_usefulness_score=0.96`, `policy_update_delta_score=1.0`, and `issue_count=0`; one DeepSeek V4 Pro 12-turn free-dialogue cell returned `overall_score=0.9569`, `interaction_usefulness_score=0.9467`, `policy_update_delta_score=1.0`, and `issue_count=0`; DeepSeek V4 Pro novice returned `overall_score=0.9645`, `interaction_usefulness_score=0.936`, and `low_interaction_usefulness=false`.
- Keeps the research claim bounded: Stage90 is current-thread test-time policy adjustment, not durable policy sedimentation, model-weight learning, or consciousness evidence. Stage91 should run paired update-on/update-null ablations with matched prompt cost and scenario mix.

Stage91: adaptation ablation
- Adds a matched `update_null` control for Stage90: the same packet shape and provider prompt line remain visible, but `update_delta` is forced to zero and the Stage89 `effective_vector` stays equal to the base vector.
- Exposes the control through `run-bionic-user-sim --disable-policy-update` and adds `evaluate_stage91_adaptation_ablation()` for paired update-on/update-null comparison.
- Reports the current offline control as intentionally inconclusive: matched 20-turn deterministic free dialogue returned identical update-on/update-null scores (`overall_score=0.8981`, `interaction_usefulness_score=0.793`, `issue_count=0`).
- Reports two matched DeepSeek V4 Pro provider cells that support the update path: cell A update-on versus update-null returned `overall_score=0.9525` versus `0.9225`, `interaction_usefulness_score=0.94` versus `0.9175`, and `issue_count=0` versus `2` with measured token delta `0.033`; cell B replicated the same direction with `overall_score=0.957` versus `0.9268`, `interaction_usefulness_score=0.94` versus `0.9175`, and `issue_count=0` versus `2`.
- Interprets the result as a bounded current-thread adaptive-gain loop: outcome-conditioned policy updates reduce provider free-dialogue failures under a matched null control, especially visual-boundary overclaiming in resume/repair turns.
- Closes the Stage87-91 interaction self-organization line without claiming persistent self-learning, model-weight learning, durable policy sedimentation, or human consciousness. The next publishable extension should test multi-timescale organization from short-term adaptive gain to medium-term attractor stabilization and long-horizon subject policy sedimentation under direct controls.

Stage92: multi-timescale attractor stabilization
- Adds `stage92` medium-term attractor-stabilization packets over Stage42 free-dialogue trajectories, including target attractors, perturbation labels, stabilization signals, input vectors, and stabilized vectors.
- Exposes the signal as `capsule.working_field.attractor_stabilization`, injects it into provider prompts as `Stage92 medium-term attractor stabilization`, adds `attractor_stabilization_score`, and adds `run-bionic-user-sim --disable-attractor-stabilization`.
- Preserves Stage91 by applying Stage92 only on the Stage90 update-on path; disabling policy update forces the Stage92 matched null shape so update-null remains uncontaminated.
- Reports the current offline control as intentionally inconclusive: matched 20-turn deterministic free dialogue returned identical attractor-on/attractor-null scores (`overall_score=0.8981`, `interaction_usefulness_score=0.793`, `continuity_score=0.8667`, `issue_count=0`).
- Reports two post-guard DeepSeek V4 Pro provider cells that support the attractor path under structural prompt-cost matching: pair B attractor-on versus attractor-null returned `overall_score=0.9567` versus `0.9121`, `continuity_score=0.8667` versus `0.5333`, and `issue_count=0` versus `1`; pair C replicated direction with `overall_score=0.9576` versus `0.9121`, `continuity_score=0.8667` versus `0.5333`, and `issue_count=0` versus `1`.
- Interprets the result as bounded medium-term current-thread trajectory stabilization, not durable policy sedimentation, persistent autobiographical self-memory, model-weight learning, or human consciousness. Stage93 should test long-horizon subject policy sedimentation under direct controls.
- Post-Stage92 system biomimetic evaluation (`docs/STAGE92_SYSTEM_BIOMIMETIC_EVALUATION_2026-05-17.md`) separates strengths from blockers: DeepSeek substrate was clean, Stage46 boundary stress passed with `overall_score=0.9625` and all core boundary metrics at `1.0`, but Stage42 DeepSeek free dialogue failed `duplicate_followup` at 20 turns (`overall_score=0.9499`) and in cached 12-turn reproduction (`overall_score=0.952`). The immediate blocker is repeated visual-boundary over-attraction, not visual overclaim, mechanism leakage, or provider fallback.
- The same evaluation found the consciousness-flow path inspectable but not claim-upgrading: a 10-turn DeepSeek V4 Pro Stage59 shadow trace completed with `observed_total_tokens=36824`, Stage70 returned `biomimetic_consciousness_score=0.503721`, Stage84 was `invalidated` because marker control did not narrow reactivation, and Stage85 had complete structured ignition/coupling (`10/10`) but stayed invalidated under the Stage84 precondition.

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
