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

## Next Program Arc (Planned)

This planned arc starts after Stage27. The durable execution sources of truth are `.agent/PLANS.md` and `.agent/STAGE23_27_PROGRAM.md`.

Online long-horizon canary
- Deferred until after Stage27 soak discipline lands and a new explicit re-plan approves any live widening.
- Any future rollout must stay host-side, shadow-first, whitelist-bound, rate-limited, rollback-safe, replay-disciplined, and action-market-first.

Artifact/tool/outcome progress coupling
- Deferred. This older Stage25 placeholder was explicitly superseded by the dense continuity scheduler milestone and should not be silently folded into Stage27 or any post-Stage27 canary work.

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
- no second brain layer
- no new unbounded always-on loop
- memory is the self
- processor is replaceable compute
- transport is eyes and hands
- action-market-first deliberation remains the decision path
