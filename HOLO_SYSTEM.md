# Holo System

Read this first if a new thread or a new agent needs to continue Holo work.

Primary handoff entry:
- `HOLO_HANDOFF.md`

## Purpose
Holo is not "a long Codex thread". Holo is an externalized persona system:
- memory is the self
- the processor is replaceable compute
- transports are just eyes and hands

The current prototype milestone is tagged as `holo-prototype`.

## Core Rule
Do not treat session continuity as identity continuity.
The real continuity lives in:
- `holo_memory_library/`
- `.holo_runtime/`
- `holo_host/`

## System Shape
1. Persona layer
- `/.holo.md`
- `holo_memory_library/session_seed.md`
- `holo_memory_library/holo_emotional_support.md`

2. Memory layer
- `canonical -> durable -> candidate -> working -> archive`
- archive is the full turn ledger
- durable is the normal prompt-facing long-term memory
- JSONL is the portable journal and sync layer
- `.holo_runtime/mind_graph.sqlite3` is the live retrieval and relationship-computation layer

3. Host kernel
- `holo_host/reply_api.py`
- `holo_host/daemon.py`
- `holo_host/store.py`
- `holo_host/processors.py`
- `holo_host/memory_bridge.py`

4. Windows transport shell
- `windows_helper/wechat_helper.py`
- `windows_helper/pyweixin_watcher.pyw`

## Main Data Flow
1. Transport receives a turn
2. Host normalizes input and builds `TurnContext`
3. Memory bridge builds a structured `mind_packet` with adaptive `fast` / `recall` tiers
4. Processor builds `TurnPlan`
4. Processor returns structured `ReplyPlan`
5. Bubble planner shapes WeChat output into 1-4 bubbles
6. Host writes outbound turn to runtime store
7. Memory bridge writes archive + working/candidate observations
8. Mind Graph incrementally re-syncs the active thread after each real turn
9. Background promotion/dream cycles adjust longer-term memory

## Current Runtime Truth
- Main processor: `codex_cli`
- Live WeChat transport: `pyweixin_dialog`
- `wcferry` is not the live path on this machine because local `Weixin 4.1.x` is incompatible with the installed `wcferry 39.x` line
- WSL kernel should be treated as authoritative; Windows helper is only a transport shell

## Mind OS V1
The in-place Mind OS refactor is now live as a repository program, not just a design note.

New foundations:
- `docs/MIND_OS_ROADMAP.md`
- `docs/rfcs/0001-mind-os-architecture.md`
- `docs/rfcs/0002-memory-substrate.md`
- `docs/rfcs/0003-processor-mesh.md`
- `holo_host/mind_graph.py`

Phase rule:
- live replies are now graph-led by default, with lane-level legacy fallback
- Mind Graph is both the memory substrate and the primary retrieval surface
- processor tasks are now typed, but `reply` remains the live default task

Current relationship-memory rule:
- a thread is not just history lines; it carries recurring motifs, unfinished lines, tone tendency, and continuity / trust / closeness scores
- these fields must survive session churn and runtime restarts because they belong to the local system, not the processor thread

## Files That Matter Most
- `HOLO_HANDOFF.md`: one-page cross-thread handoff entry
- `HOLO_HOST.md`: host and runtime behavior
- `OPERATIONS.md`: how to start, stop, inspect, and recover the system
- `holo_memory_library/MEMORY_LIBRARY.md`: memory architecture and CLI
- `windows_helper/README.md`: Windows transport details
- `tests/`: regression coverage for host, memory, and Windows helper

## Invariants
- Do not let a transport silently fall back to a different online mode
- Do not store internal prompts, rewrite reasons, or hook control text as user memory
- Do not let fast-path WeChat replies truncate into half-sentences
- Do not let runtime state be the only source of history; archive must remain the durable ledger
- Do not depend on one Codex chat thread to keep Holo alive
- Do not treat `codex_session_id` as memory; it is only a resumable compute cache
- Do not let WeChat single chats split into `wechat:<name>` and `<name>` alias threads
- Do not publish live memory JSONL or runtime graph state to a public remote; memory sync belongs only on trusted local/private paths

## Current Weak Spots
- `pyweixin_dialog` on `Weixin 4.1` is usable but still the most fragile part
- live trigger behavior still needs more real-world hardening
- image understanding is still "artifact + sidecar text + metadata first", not a fully native visual stack
- latency still needs more fast-path tuning

## What To Update When You Change Holo
If a thread changes runtime behavior, also update:
- `HOLO_HANDOFF.md`
- `HOLO_SYSTEM.md`
- `HOLO_DEVELOPMENT.md`
- `HOLO_HOST.md`
- `OPERATIONS.md`
- tests covering the changed path
