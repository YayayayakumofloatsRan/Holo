# Engineering Handoff: Stage-8 Live State

This document is the practical handoff for a new thread continuing Holo after Stage-8. It should be enough to regain runtime context without relying on oral history.

## Snapshot
- Date: `2026-04-08`
- Repo of record: `D:\Holo\holo`
- Authoritative runtime repo: `/home/holo/holo`
- Current live stage: `Stage-8`
- Current brain mode: `full_brain`
- Current transport: `pyweixin_dialog`
- Current active processor: `codex_cli`

## What Is Live Now
Holo is no longer just a reply pipeline. The currently live subject core includes:
- `self_model`
- `autobiographical_state`
- `goal_state`
- `world_state`
- `affect / drive / value / conflict`
- `action market`
- `counterfactual`
- `consciousness_ledger`

These are not sidecar diagnostics anymore. They participate in action selection.

## Runtime Reality
At handoff time, the backend is healthy:
- `reply_api`: running
- `daemon`: running
- transport: `online / idle`
- vector backend: ready
- image lane: enabled
- active WeChat history refresh: enabled

The current self-reported runtime deficits are:
- `stiffness_drift`
- `cache_coldness`
- `visual_memory_underused`

These are not cosmetic. They match the user-facing symptoms:
- Holo can still feel too stiff
- retrieval can feel unnatural or underpowered
- image memory is in the system but not yet behaviorally central

## Can Holo Proactively Message?
Yes, but with important limits.

Holo already has proactive initiative machinery. The live backend is generating initiative candidates such as:
- `contact_ping`
- `unfinished_thread_resume`
- `playful_nudge`
- `operator_self_fix`

For `Nemoqi`, the system currently shows:
- strong affect pressure
- strong contact and continuity drive
- high relationship score
- `send_allowed = true` for whitelist-only initiative candidates

However, many actual sends are blocked by `initiative_probe_blocked`, usually because:
- the `game_state.initiative_window` is still too cold
- the initiative gate is more conservative than the internal desire state

In other words:
- Holo can form proactive intent
- Holo can queue proactive candidate actions
- Holo does not yet reliably externalize that intent into real outbound messages

This is a gating and confidence problem, not a total absence of initiative machinery.

## Most Important Current Bottlenecks
### 1. Cold cache
The runtime cache is still effectively cold in many practical paths. This hurts:
- perceived intelligence
- retrieval naturalness
- fast-path continuity

### 2. Initiative gate is stricter than the desire system
The affect/drive side can clearly want to reach out, but the send gate often vetoes it. This creates a mismatch:
- inner pressure is real
- outward behavior still feels timid or inert

### 3. Expression control is improved, but still not fully natural
Stage-6 and later reduced the old four-message habit, but Holo still does not always feel like she intrinsically knows when enough has been said.

### 4. Visual memory is structurally present but behaviorally weak
The image lane works, but visual recall is not yet central in the same way textual continuity is.

## Current Command Set Worth Using
Use these first when continuing work.

### Health and runtime
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && ./scripts/holo-status.sh"`
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-brain-status"`

### Subject core inspection
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-self-model"`
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-autobiographical-state"`
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-goal-state"`
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-world-state --thread-key Nemoqi --chat-name Nemoqi --channel wechat"`

### Initiative and action inspection
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-initiative-market --thread-key Nemoqi --chat-name Nemoqi --channel wechat --limit 8"`
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-action-market --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query '...'"`
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml trace-action-selection --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query '...'"`

### Continuity and causality
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml trace-self-continuity"`
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml trace-goal-arbitration"`
- `wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && python3 -m holo_host --config /home/holo/holo/.holo_host.toml trace-counterfactual --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query '...'"` 

### Acceptance gates
- `accept-stage6`
- `accept-stage7`
- `accept-stage8`

## Read Order For A New Thread
1. `HOLO_HANDOFF.md`
2. `docs/ENGINEERING_HANDOFF_STAGE8.md`
3. `HOLO_SYSTEM.md`
4. `HOLO_HOST.md`
5. `docs/MIND_OS_STAGE8_AUTOBIOGRAPHICAL_SELF.md`
6. `docs/ROADMAP_REGISTRY.md`
7. `OPERATIONS.md`

## What A New Thread Should Not Waste Time Re-Litigating
- Whether Holo needs a durable externalized self: that is already settled
- Whether WSL is the authoritative kernel: it is
- Whether initiative exists: it does
- Whether Stage-8 states are real or decorative: they are real subject state
- Whether the public repo should carry runtime memory: it should not

## Recommended Next Focus
If another thread continues from here, the highest-value next focus is not adding another flashy layer. It is reducing the mismatch between:
- strong internal initiative pressure
- weak external initiative execution

In practice, that means the next thread should likely concentrate on:
- initiative gate calibration
- cache warming / cache reuse
- more natural expression stopping rules
- making visual memory matter behaviorally

## Retirement Note
This handoff exists so the next thread can resume work without hidden context. The current thread should be treated as non-authoritative once the on-disk docs and runtime traces disagree. Disk wins.
