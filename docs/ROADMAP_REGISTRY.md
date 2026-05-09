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

## Next Program Arc (Planned)

This planned arc starts after Stage34. The durable execution sources of truth remain `.agent/PLANS.md` and `.agent/STAGE23_27_PROGRAM.md` until a Stage35+ program replaces them.

Provider/API compatibility breadth
- Partially implemented through Stage29 DeepSeek text support, Stage31 adapter registry, Stage33 provider contract diagnostics, and Stage34 visual-readiness gating.
- Future work should broaden API/provider compatibility through the processor fabric, not by adding raw hot-path provider calls.
- Visual-provider hardening should validate real configured `image_understand` lanes before Holo is restarted; Stage34 only proves the offline contract does not overclaim image support.

Bionic workflow hardening
- Partially implemented through Stage30 subject-loop invariants, Stage31 subject-loop diagnostics, Stage32 response shaping, and Stage34 debt classification. Future work should improve autonomous inquiry shape without adding a second brain.

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
