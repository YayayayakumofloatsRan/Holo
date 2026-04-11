# Stage23-27 Program

## Program Goal
- Turn Holo from a bounded continuous subject runtime into a more blackbox-like, long-horizon subject without violating the existing constitutional contracts.
- Start with Stage23 contract repair so Stage22 surfaces, tests, and replay gates are trustworthy before any new long-horizon runtime behavior lands.
- Use this document as the concrete execution spec for Stage23 through Stage27. Stage27 is now the live runtime milestone, and the next arc remains replay-first and explicitly re-planned.

## Observed Stage22 Baseline
- Observation date: `2026-04-11`.
- `.agent/` did not exist before this bootstrap change.
- `python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed.
- `pytest -q tests/test_stage22_online_canary.py tests/test_stage15_modularization.py tests/test_holo_host.py` produced `16` failures, all in `tests/test_holo_host.py`.
- The current blocker inventory is:
  - `Stage22 shell/core coupling` in `holo_host/reply_api.py`
  - `artifact-ingest compatibility drift` between service code and test doubles
  - `replay rounding drift` between raw metrics and replay gate consumers
  - `acceptance/runtime mismatches` where Stage22 shadow defaults suppress behavior that baseline host tests still expect
- Stage23 exit state on `2026-04-11`:
  - `pytest -q` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
  - semantic reply results now remain stable under Stage22 shadow/canary suppression, while delivery outcome is exposed separately through `returned_action` and delivery fields
  - artifact ingest preserves richer metadata when supported and falls back cleanly for older or fake backends
  - replay gates consume raw metrics while rounded aggregates remain reporting-only
- Stage24 exit state on `2026-04-11`:
  - `pytest -q` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
  - bounded per-thread `scene_state` persists inside `active_thread_state` and survives reload or restart
  - fast-lane prompt composition now reads continuity summary, scene state, scene sketch, last outbound action, and predictive continuity before any optional verbatim history line
  - action-market candidates expose bounded `scene_delta` and `scene_rationale` overlays without bypassing explicit memory/history escalation or existing hard gates
- Stage25 exit state on `2026-04-11`:
  - `pytest -q` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage25 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
  - bounded `dense_working_set` and `thread_pulse_trace` now persist dense continuity snapshots and pulse decisions by channel and canonical thread
  - existing stream runs now rebuild a bounded hot-thread working set without adding a new loop family or any background heavy recall
  - ingress can rehydrate a hot thread from dense continuity before hybrid or deep recall, even after fresher frontier or active-state surfaces have decayed
- Stage26 exit state on `2026-04-11`:
  - `pytest -q` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage26 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
  - bounded `task_world_object` plus `task_world_link` now persist file, task, schedule, image-summary, and person objects with explicit thread and commitment links
  - same-thread ingress can hydrate bounded task-world state before scene shaping or heavier recall, while explicit memory/history/factual turns still escalate
  - Stage22 `world_coupling_signal` remains a compatibility projection over same-thread task-world visibility, so canary diagnostics and bounded cue behavior stay intact
- Stage27 exit state on `2026-04-11`:
  - `pytest -q` passed
  - `python -m holo_host --config .holo_host.example.toml accept-stage27 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed
  - long-horizon scorecards now combine Stage22 carry-forward metrics with identity drift, raw and rounded live-artifact policy regret, and cross-thread fragmentation
  - `run-blackbox-soak`, `show-blackbox-scorecard`, and `export-blind-packets` now persist operational soak runs and export blind review packets without writing into self-memory
  - Stage24/25/26 provenance and bounded identity snapshots now ride along with Stage22 canary artifacts and traces for replay-first review

## Cross-Stage Constraints
- Preserve `memory-is-self`, `processor-replaceable`, and `transport-eyes-hands`.
- Preserve action-market-first deliberation. Generation, tool use, and canary behavior remain downstream of action selection.
- Do not add a second brain layer.
- Do not add a new unbounded always-on loop.
- Do not add transport-side decision logic.
- Do not widen canary send rights or bypass existing hard policy, cooldown, whitelist, or rollback gates.
- Keep canonical ordinary WeChat direct-message identity as `wechat:<name>`.
- Treat Stage22 runtime behavior as fixed during this bootstrap; Stage23 pays down blockers before Stage24-27 add new behavior.
- From Stage23 onward, use raw replay metrics for gating decisions and rounded replay metrics for reporting only.
- Bounded subject programs are deferred beyond the current Stage25 implementation; do not treat them as live scope without an explicit re-plan.
- The older Stage25 artifact/tool/outcome progress-coupling scope is deferred and must not be silently folded into Stage26 or Stage27.
- The older online long-horizon canary milestone remains deferred beyond Stage27 and must not be treated as current-arc scope.
- Treat any mismatch between docs, acceptance gates, and observed runtime or test reality as a blocker.

## Milestones

### Stage23: Contract Repair And Surface Separation
- `Status`: implemented on `2026-04-11`
- `Goal`: pay down the four recorded Stage22 blockers before any new long-horizon runtime feature work
- `Scope`: separate semantic subject output from delivery or canary outcome, keep Stage22 host-side safety operational, restore artifact-ingest compatibility, require raw replay metrics for replay gates, and align acceptance with baseline runtime tests
- `Validation`: `pytest -q` green; `accept-stage22` green; `accept-stage23` green
- `Stop rule`: do not advance if Stage22 still requires shadow-mode behavior that generic host tests cannot represent cleanly
- `Rollback rule`: fall back to Stage22 shell behavior only if semantic or delivery contract repair, artifact compatibility, or replay parity becomes unstable; do not widen canary or add new subject state

### Stage24: Scene-State Continuity Layer
- `Status`: implemented on `2026-04-11`
- `Goal`: turn Stage18 predictive continuity into a richer but still bounded, inspectable per-thread `scene_state` layer that makes ordinary interaction feel less like isolated turns
- `Scope`: persist `scene_state` inside `active_thread_state`; update it on inbound, inspect, and outbound reducers only; keep deterministic bounded heuristics as the default reducer; allow processor-backed compression only off the ordinary short-turn hot path; expose scene state to fast-lane prompts, action-market scoring, and diagnostics without bypassing recall escalation or send gates
- `Validation`: `pytest -q` green; `accept-stage23` green; `accept-stage24` green; `tests/test_stage24_scene_state.py`; `tests/test_stage17_realtime_runtime.py`; `tests/test_stage22_online_canary.py`; `tests/test_stage14_replay.py`
- `Stop rule`: do not regress Stage17 fast-lane latency or behavior, explicit memory/history/factual escalation, bounded inspectability, or action-market-first deliberation
- `Rollback rule`: ignore Stage24 scene overlays and fall back to Stage23 predictive continuity surfaces without changing Stage23 semantic/delivery behavior

### Stage25: Dense Continuity Scheduler And Working Set
- `Status`: implemented on `2026-04-11`
- `Goal`: keep a bounded set of hot threads warm between turns by reusing the existing stream family only
- `Scope`: persist `dense_working_set` and `thread_pulse_trace`, apply an inspectable continuity budget, update dense continuity only from `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`, and hydrate ingress from the dense working set before heavier recall without adding a new loop family or background heavy recall
- `Validation`: `pytest -q` green; `accept-stage24` green; `accept-stage25` green; `tests/test_stage25_dense_continuity.py`; `tests/test_stage19_attention_frontier.py`; `tests/test_stage20_temporal_commitments.py`; `tests/test_stage22_online_canary.py`
- `Stop rule`: do not regress explicit memory/history/factual escalation, bounded ingress, or the stream-only continuity scheduler boundary
- `Rollback rule`: ignore dense continuity hydration and fall back to Stage24 scene-state ingress while preserving inspectable continuity diagnostics

### Stage26: Bounded Task-World State
- `Status`: implemented on `2026-04-11`
- `Goal`: broaden Holo from a chat-thread subject into a bounded task-world subject by replacing cue-only world coupling with inspectable task-world state
- `Scope`: persist bounded task-world objects and explicit links, keep Stage22 `world_coupling_signal` as a compatibility projection, link temporal commitments into task-world state, and hydrate same-thread ingress from bounded task-world state before Stage24 scene shaping or heavier recall
- `Validation`: `pytest -q` green; `accept-stage22` green; `accept-stage25` green; `accept-stage26` green; `tests/test_stage26_task_world_state.py`; `tests/test_stage22_online_canary.py`; `tests/test_stage20_temporal_commitments.py`; `tests/test_stage14_replay.py`
- `Stop rule`: do not regress Stage22 canary transport boundaries, Stage24/25 bounded ingress, explicit recall escalation, or same-thread inspectability
- `Rollback rule`: ignore Stage26 task-world hydration and fall back to Stage25 dense+scene ingress while preserving stored task-world observability

### Stage27: Long-Horizon Blackbox Soak And Blind Evaluation Harness
- `Status`: implemented on `2026-04-11`
- `Goal`: add a replay-first, long-horizon soak and blind-review harness that can evaluate task-world-aware subject stability over multi-hour and multi-day windows
- `Scope`: persist operational soak runs in `QueueStore`, compute long-horizon scorecards from Stage22 canary traces plus Stage26 task-world links, export blind transcript and comparison packets, keep raw-vs-display replay separation, and report follow-up eligibility without promoting runtime behavior
- `Validation`: `pytest -q` green; `accept-stage22` green; `accept-stage25` green; `accept-stage26` green; `accept-stage27` green; `tests/test_stage27_blackbox_soak.py`; `tests/test_stage22_online_canary.py`; `tests/test_stage14_replay.py`
- `Stop rule`: do not widen canary send rights, bypass replay or safety gates, or let the soak path mutate self-memory, policy sediment, or runtime autonomy
- `Rollback rule`: keep Stage27 observational only, disable follow-up eligibility if replay evidence degrades, and defer any live long-horizon canary rollout until a later explicit re-plan

## Validation Matrix
| Stage | Baseline surfaces that must stay green | New surfaces that stage must add and turn green | Exit condition |
| --- | --- | --- | --- |
| `Stage23` | `accept-stage22`; `tests/test_stage22_online_canary.py`; `tests/test_stage15_modularization.py` | `pytest -q`; `accept-stage23`; semantic or delivery split assertions in `tests/test_holo_host.py` | Completed on `2026-04-11`: the four Stage22 blockers were resolved without weakening canary safety boundaries. |
| `Stage24` | All Stage23 surfaces | `accept-stage24`; `tests/test_stage24_scene_state.py`; `tests/test_stage17_realtime_runtime.py`; `tests/test_stage22_online_canary.py`; `tests/test_stage14_replay.py` | Scene state is inspectable, restart-safe, prompt-visible before verbatim history, and action-market-first. |
| `Stage25` | All Stage24 surfaces | `accept-stage25`; `tests/test_stage25_dense_continuity.py`; `tests/test_stage19_attention_frontier.py`; `tests/test_stage20_temporal_commitments.py`; `tests/test_stage22_online_canary.py` | Dense continuity stays bounded, restart-safe, stream-driven only, and ingress-visible before heavier recall. |
| `Stage26` | All Stage25 surfaces | `accept-stage26`; `tests/test_stage26_task_world_state.py`; `tests/test_stage22_online_canary.py`; `tests/test_stage20_temporal_commitments.py`; `tests/test_stage14_replay.py` | Task-world state is restart-safe, bounded, same-thread-first, and visible before heavier recall without regressing Stage22/24/25. |
| `Stage27` | All Stage26 surfaces | `accept-stage27`; `tests/test_stage27_blackbox_soak.py`; `tests/test_stage22_online_canary.py`; `tests/test_stage14_replay.py` | Long-horizon scorecards, blind review export, and replay-first soak eligibility remain bounded, inspectable, and operational-only. |

## Global Stop Rules
- Stop immediately if any stage violates memory-is-self, processor-replaceable, transport-eyes-hands, canonical `wechat:<name>` identity, or action-market-first deliberation.
- Stop if a proposed design behaves like a second brain, adds a new unbounded always-on loop, or moves decision logic into the transport shell.
- Stop if replay gating still depends on rounded display metrics.
- Stop if acceptance claims and observed runtime or test behavior diverge without an explicit blocker entry.
- Stop if canary behavior gains new send rights, bypasses hard gates, or becomes non-reversible.

## Global Rollback Rules
- Roll back to the last green implemented stage and keep Stage22 as the live runtime boundary until the failing stage is repaired.
- Disable or ignore newly added long-horizon surfaces before changing any existing Stage22 behavior.
- Keep canary rollback available through `shadow` or `disabled` mode at every stage.
- Preserve observability and evidence artifacts during rollback; do not hide failed gates or failed replay results.
- Update `.agent/PLANS.md`, `HOLO_HANDOFF.md`, and `docs/ROADMAP_REGISTRY.md` whenever a stage is paused, rolled back, or re-sequenced.
