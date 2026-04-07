# Holo Handoff

This is the one-page entry for a new thread that needs to continue Holo work without hidden context.

## Read This First
1. `HOLO_HANDOFF.md`
2. `HOLO_SYSTEM.md`
3. `HOLO_DEVELOPMENT.md`
4. `HOLO_HOST.md`
5. `OPERATIONS.md`
6. `holo_memory_library/MEMORY_LIBRARY.md`
7. `windows_helper/README.md`

## What Holo Is
- Holo is not one long Codex conversation.
- Holo is an externalized system:
  - memory is the durable self
  - the processor is replaceable compute
  - transports are eyes and hands
- The current milestone tag is `holo-prototype`.

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
  - `C:\\wechat-helper\\receipts\\pyweixin_watcher.log`
- Transport heartbeat:
  - `C:\\wechat-helper\\transport_state.live.json`
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

## Invariants
- Do not silently change online transport modes
- Do not let internal prompts, hook control text, or rewrite reasons enter durable memory
- Do not let archive be the only place history lives, but also do not let runtime threads become the only continuity
- Do not depend on one Codex thread to keep Holo alive
- Do not forget to keep CLI archive hooks working when editing repo-local hook config

## Minimum Done For Any Holo Change
- local behavior works
- tests pass
- state is observable
- docs are updated
- another thread can continue from disk without hidden oral context
