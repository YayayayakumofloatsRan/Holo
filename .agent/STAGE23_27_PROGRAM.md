# Stage23-27 Program

## Program Goal
- Turn Holo from a bounded continuous subject runtime into a more blackbox-like, long-horizon subject without violating the existing constitutional contracts.
- Start with Stage23 contract repair so Stage22 surfaces, tests, and replay gates are trustworthy before any new long-horizon runtime behavior lands.
- Use this document as the concrete execution spec for Stage23 through Stage27. Stage23 is now the live runtime milestone, and Stage24 is the next planned implementation focus.

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
- Treat any mismatch between docs, acceptance gates, and observed runtime or test reality as a blocker.

## Milestones

### Stage23: Contract Repair And Surface Separation
- `Status`: implemented on `2026-04-11`
- `Goal`: pay down the four recorded Stage22 blockers before any new long-horizon runtime feature work
- `Scope`: separate semantic subject output from delivery or canary outcome, keep Stage22 host-side safety operational, restore artifact-ingest compatibility, require raw replay metrics for replay gates, and align acceptance with baseline runtime tests
- `Validation`: `pytest -q` green; `accept-stage22` green; `accept-stage23` green
- `Stop rule`: do not advance if Stage22 still requires shadow-mode behavior that generic host tests cannot represent cleanly
- `Rollback rule`: fall back to Stage22 shell behavior only if semantic or delivery contract repair, artifact compatibility, or replay parity becomes unstable; do not widen canary or add new subject state

### Stage24: Bounded Subject Programs
- `Status`: planned
- `Goal`: introduce the long-horizon unit as a bounded, inspectable subject-program surface rather than a hidden planner
- `Scope`: define program records keyed by canonical thread plus bounded program id, carrying objective, current step, blocker, due window, evidence refs, and last outcome; hydration must stay same-thread and action-market-first
- `Validation`: explicit program packet fields, restart-safe persistence, no send permission change, no recall trigger by program state alone, and canonical-thread isolation
- `Stop rule`: do not advance if the design starts acting like a second brain or requires a new always-on loop
- `Rollback rule`: degrade the program surface to empty or ignored state without changing Stage23 behavior

### Stage25: Artifact/Tool/Outcome Progress Coupling
- `Status`: planned
- `Goal`: make artifacts, tool outcomes, deferred replies, and world cues update the same bounded long-horizon program surface
- `Scope`: unify artifact, task, schedule, file, image, and lookup outcomes as bounded progress reducers with dedupe and evidence refs; no transport-side decisions and no direct execution rights
- `Validation`: same-thread progress updates, cross-thread leakage blocked, explicit memory/history requests still escalate, and artifact-ingest contracts remain compatible across service code, memory bridge, and tests
- `Stop rule`: do not advance if ingest surfaces fork into incompatible schemas again
- `Rollback rule`: disable progress reducers while preserving Stage24 program read surfaces

### Stage26: Long-Horizon Replay And Promotion Gates
- `Status`: planned
- `Goal`: extend replay discipline from short-turn calibration to multi-step program quality
- `Scope`: add multi-step replay fixtures, raw-vs-display metric separation, and promotion or rollback rules that use raw metrics only for gating and rounded metrics only for reporting
- `Validation`: deterministic replay across reruns, raw metrics exposed beside rounded metrics, no gating decision made from display-rounded values, and regret non-worsening across promoted behavior
- `Stop rule`: do not advance if replay cannot explain why a multi-step behavior was approved or rejected
- `Rollback rule`: disable promotion of long-horizon overlays and keep replay observational only

### Stage27: Online Long-Horizon Canary
- `Status`: planned
- `Goal`: canary program-aware long-horizon behavior online without granting uncontrolled autonomy
- `Scope`: host-side, shadow-first rollout for program-aware decisions with whitelist, rate limits, rollback switch, observable telemetry, and replay-on-live-artifacts; no new unbounded loop and no send-permission bypass
- `Validation`: default shadow suppression, reversible canary-live gates, program telemetry visible, replay artifacts generated, and Stage23-26 validations still green
- `Stop rule`: do not advance if online canary requires watcher logic, hidden state mutation, or bypasses existing hard gates
- `Rollback rule`: set canary back to `shadow` or `disabled` and ignore program-aware live behavior while preserving stored observability

## Validation Matrix
| Stage | Baseline surfaces that must stay green | New surfaces that stage must add and turn green | Exit condition |
| --- | --- | --- | --- |
| `Stage23` | `accept-stage22`; `tests/test_stage22_online_canary.py`; `tests/test_stage15_modularization.py` | `pytest -q`; `accept-stage23`; semantic or delivery split assertions in `tests/test_holo_host.py` | Completed on `2026-04-11`: the four Stage22 blockers were resolved without weakening canary safety boundaries. |
| `Stage24` | All Stage23 surfaces | Planned `accept-stage24`; planned `tests/test_stage24_subject_programs.py`; `tests/test_stage14_replay.py` | Bounded subject programs are inspectable, restart-safe, and action-market-first. |
| `Stage25` | All Stage24 surfaces | Planned `accept-stage25`; planned `tests/test_stage25_progress_coupling.py`; artifact-ingest compatibility checks across service and memory layers | Artifacts, tools, deferred replies, and world cues update the same bounded program surface without schema drift. |
| `Stage26` | All Stage25 surfaces | Planned `accept-stage26`; planned `tests/test_stage26_long_horizon_replay.py`; `tests/test_stage14_replay.py` with raw-vs-rounded checks | Replay and promotion gates use raw metrics for decisions and keep rounded metrics as reporting only. |
| `Stage27` | All Stage26 surfaces | Planned `accept-stage27`; planned `tests/test_stage27_long_horizon_canary.py`; `replay-live-artifacts` remains usable on program-aware traces | Program-aware long-horizon online canary remains host-side, shadow-first, bounded, reversible, and replay-disciplined. |

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
