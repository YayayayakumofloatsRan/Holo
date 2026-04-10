# Stage22 Bounded Blackbox Online Canary

## Goal

Stage22 moves Holo from self-shaping subject runtime toward bounded live blackbox approximation. The implementation is host-side and shadow-first: `/reply` still enters through MemoryBridge and the action market, but Stage22 can record would-have behavior, compute live metrics, and suppress live sends unless canary gates pass.

Default rollout is `shadow`. `canary_live` must be explicitly configured and still requires whitelist, rate limits, clear rollback switch, existing policy, and action-market-selected behavior.

## Boundary

- No uncontrolled autonomy.
- No hidden live self-modification.
- No watcher-side decision layer.
- No new loop family.
- No bypass of processor fabric or the action market.
- No direct send permission grant from Stage22.
- No world-coupling cue triggers vector or graph recall by itself.
- Windows helper remains eyes and hands only.

## Runtime Surfaces

Config under `[autonomy]`:

- `stage22_canary_mode`: `disabled`, `shadow`, or `canary_live`
- `stage22_canary_whitelist_threads`
- `stage22_canary_max_replies_per_thread_per_hour`
- `stage22_canary_max_replies_global_per_hour`
- `stage22_canary_artifact_capture`
- `stage22_canary_artifact_root`
- `stage22_canary_rollback_file`

QueueStore owns operational telemetry:

- `online_canary_traces`
- event, thread, channel, chat name, message id
- mode and verdict
- selected action and returned action
- latency bucket
- artifact path
- compact Stage18-21 trace metadata

Mind Graph owns bounded perception cues:

- `world_coupling_signal`
- cue types: `file_artifact`, `image_summary`, `schedule_cue`, `task_cue`
- same-thread hydration, max 3 cues
- status and stale time determine whether a cue is visible

## Reply Gate

The Stage22 gate runs after sidecar/action-market selection and before tool use, deferred jobs, history refresh, or generation.

Modes:

- `disabled`: preserves current behavior and records no Stage22 canary trace.
- `shadow`: records canary artifact and returns a non-sendable `silence` response with `stage22_shadow=true`.
- `canary_live`: continues only when the canonical thread is whitelisted, hourly limits are open, rollback file is absent, and existing downstream policy still allows the selected behavior.

The gate can block or suppress only. It never chooses a new action.

## Metrics

Stage22 exposes deterministic blackbox metrics from canary traces:

- reflex-hit rate
- reread-history rate
- clarification thrash rate
- duplicate followup rate
- resume success after interruption
- latency buckets by action type

These are observational evidence. Stable behavior changes still go through Stage21 replay-gated sedimentation.

## Live Artifact Replay

Canary artifacts are written under:

```text
artifacts/canary/stage22/YYYYMMDD/
```

`replay-live-artifacts` converts captured canary artifacts into temporary Stage14 fixture JSON and runs the existing Stage14 replay harness. This is an explicit command, not a daemon loop.

## Diagnostics

```bash
python -m holo_host show-online-canary
python -m holo_host show-blackbox-metrics --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host trace-canary-decision --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "still here?"
python -m holo_host set-canary-rollback --enabled true --reason manual_hold
python -m holo_host set-canary-rollback --enabled false --reason clear_hold
python -m holo_host replay-live-artifacts --since-hours 24
python -m holo_host show-world-coupling --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

HTTP/service surfaces mirror the CLI:

- `/online-canary`
- `/blackbox-metrics`
- `/canary-decision`
- `/canary-rollback`
- `/replay-live-artifacts`
- `/world-coupling`
- `/accept-stage22`

## Acceptance

Closure command:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The gate verifies:

- shadow mode captures artifacts and suppresses live sends
- `canary_live` gates require whitelist, rate limits, and clear rollback switch
- rollback switch is reversible
- live artifacts feed Stage14 replay
- blackbox metrics are visible
- world-coupling cues hydrate same-thread state without heavy recall
- canonical WeChat identity remains `wechat:<name>`
- Stage21 acceptance remains green

Required regressions:

```bash
pytest -q tests/test_stage22_online_canary.py tests/test_stage21_policy_sedimentation.py tests/test_stage20_temporal_commitments.py
pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py
python -m holo_host --config .holo_host.example.toml accept-stage21 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

## Regression Risks

- `shadow` accidentally sends a reply.
- `canary_live` proceeds without whitelist, rate, or rollback checks.
- Watcher code starts making send decisions.
- Artifact capture becomes durable self-memory instead of operational telemetry.
- World-coupling cues become an implicit recall trigger.
- Live artifacts skip Stage14 replay discipline.

## Rollback

Set the rollback file through:

```bash
python -m holo_host set-canary-rollback --enabled true --reason emergency_hold
```

For a hard runtime rollback, set `stage22_canary_mode = "disabled"`. Existing Stage18-21 subject runtime remains intact.
