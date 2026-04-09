# Holo Handoff

This is the one-page entry for a new thread that needs to continue Holo work without hidden context.

## Read This First
1. `HOLO_HANDOFF.md`
2. `docs/ENGINEERING_HANDOFF_STAGE8.md`
3. `docs/ENGINEERING_HANDOFF_STAGE9.md`
4. `docs/WECHAT_WATCHER_INTERFACE_CONTRACT.md`
5. `docs/STAGE9_INTELLIGENCE_AND_CODEX_COST.md`
6. `HOLO_SYSTEM.md`
7. `HOLO_DEVELOPMENT.md`
8. `HOLO_HOST.md`
9. `OPERATIONS.md`
10. `holo_memory_library/MEMORY_LIBRARY.md`
11. `windows_helper/README.md`

## What Holo Is
- Holo is not one long Codex conversation.
- Holo is an externalized system:
  - memory is the durable self
  - the processor is replaceable compute
  - transports are eyes and hands
- The current milestone tag is `stage9-adaptive-initiative-gate`.

## Source Of Truth
- Persona and prompt bones:
  - `/.holo.md`
  - `holo_memory_library/session_seed.md`
  - `holo_memory_library/holo_emotional_support.md`
- Runtime kernel:
  - `holo_host/`
- Long-term and working memory:
  - `holo_memory_library/`
- Operations and recovery:
  - `scripts/`
  - `OPERATIONS.md`
- Windows transport shell:
  - `windows_helper/`

## Current Runtime Truth
- Active processor: `codex_cli`
- Active WeChat online path on this machine: `pyweixin_dialog`
- `wcferry` is diagnostic-only here because local `Weixin 4.1.x` is incompatible with installed `wcferry 39.x`
- WSL is the authoritative kernel
- Windows helper is only the transport shell
- Default brain mode is `full_brain`
- Stage-8 is live:
  - `autobiographical_state`
  - `goal_state`
  - `world_state`
  - `counterfactual`
  - `consciousness_ledger`
- Holo can generate proactive initiative candidates, but current gates are conservative and often block auto-send.
- Stage-9 adaptive initiative gate is implemented in code; rollout should still start from `initiative_gate_mode=conservative` before switching default behavior to `adaptive`.

## Memory Pyramid
- `canonical`: persona core and non-negotiable boundaries
- `durable`: stable long-term memory used in prompt assembly
- `candidate`: emerging patterns waiting for promotion
- `working`: short-lived active observations
- `archive`: full turn ledger, not prompt-facing by default

## Full Dialogue Archive
- Full turn archive file:
  - `holo_memory_library/memories/conversation_archive.jsonl`
- CLI conversations are also archived when repo-local Codex hooks are active:
  - `/.codex/hooks.json`
  - `holo_memory_library/codex_hooks/user_prompt_submit.py`
  - `holo_memory_library/codex_hooks/stop_revise.py`
- Quick check for recent CLI archive rows:
  - `python3 holo_memory_library/rag_memory.py show-archive --channel codex_cli --limit 5`

## Mutable Runtime State
These files change while Holo is alive. Do not treat them like static docs.
- `.holo_runtime/`
- `.holo_runtime/mind_graph.sqlite3`
- `holo_memory_library/memories/working_store.jsonl`
- `holo_memory_library/memories/candidate_store.jsonl`
- `holo_memory_library/memories/memory_store.jsonl`
- `holo_memory_library/memories/conversation_archive.jsonl`
- `holo_memory_library/memories/emotion_trace.jsonl`
- `holo_memory_library/memories/callback_candidates.jsonl`

## Start, Stop, Inspect
- Start all:
  - `./scripts/holo-start-all.sh`
- Stop all:
  - `./scripts/holo-stop-all.sh`
- Restart all:
  - `./scripts/holo-restart-all.sh`
- Status:
  - `./scripts/holo-status.sh`

## When A New Thread Starts Work
1. Read the docs above in order.
2. Run `./scripts/holo-status.sh`.
3. Check whether Holo is supposed to stay online before touching runtime files.
4. Run targeted tests before editing.
5. Make one focused change.
6. Re-run relevant tests.
7. Update docs if runtime behavior, memory semantics, or operator workflow changed.

## Where To Look First When Something Breaks
- Kernel health:
  - `./scripts/holo-status.sh`
- WSL runtime logs:
  - `.holo_runtime/logs/`
- Windows watcher log:
  - `.holo_runtime/wechat-helper/receipts/pyweixin_watcher.log`
- Transport heartbeat:
  - `.holo_runtime/wechat-helper/transport_state.live.json`
- Runtime message store:
  - `.holo_runtime/holo_host.sqlite3`
- Mind Graph:
  - `.holo_runtime/mind_graph.sqlite3`
- Full archive:
  - `holo_memory_library/memories/conversation_archive.jsonl`

## Current Weak Spots
- `pyweixin_dialog` on `Weixin 4.1` is still the most fragile live layer
- live WeChat trigger behavior still needs real-world hardening
- image understanding is still artifact-first, not a fully native visual stack
- latency and fast-path tuning still need work
- cache reuse is still cold in practice
- proactive initiative exists but is often blocked by `initiative_probe_blocked`
- retrieval and expression control still feel more engineered than natural
- main-brain override and initiative gate calibration can create false negatives under cold `initiative_window` states
- token usage is still not metered per task or per loop

## Stage-9 Focus
- goal: remove over-conservative proactive gating while preserving hard safety constraints
- hard_gate: non-overridable constraints such as whitelist policy, cooldown, per-thread allow flag, policy decision, and explicit disable
- soft_gate: `trust`, `initiative_window`, `drive_pressure`, `pressure_level` become directional scoring inputs
- main_brain_override: allowed only when gate is soft-blocked and mode is healthy; never bypasses hard_gate
- rollout: begin in `initiative_gate_mode=conservative`, verify, then switch default to adaptive

## Stage-9 Entry Commands
- `python3 -m holo_host initiative-probe --thread-key Nemoqi --chat-name Nemoqi`
- `python3 -m holo_host show-initiative-status --thread-key Nemoqi --chat-name Nemoqi`
- `python3 -m holo_host accept-stage9 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host accept-stage8 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`

## Invariants
- Do not silently change online transport modes
- Do not touch the watcher path without reading `docs/WECHAT_WATCHER_INTERFACE_CONTRACT.md`
- Do not let internal prompts, hook control text, or rewrite reasons enter durable memory
- Do not let archive be the only place history lives, but also do not let runtime threads become the only continuity
- Do not depend on one Codex thread to keep Holo alive
- Do not forget to keep CLI archive hooks working when editing repo-local hook config
- Do not treat `autobiographical_state`, `goal_state`, or `world_state` as display-only metadata; they are now part of subject deliberation
- Do not publish live memory or runtime state to the public repo

## Minimum Done For Any Holo Change
- local behavior works
- tests pass
- state is observable
- docs are updated
- another thread can continue from disk without hidden oral context
- when `accept-stage9` is available, run it before and after any gate-mode transition
