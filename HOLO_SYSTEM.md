# Holo System

Read this first if a new thread or a new agent needs to continue Holo work.

Primary handoff entry:
- `HOLO_HANDOFF.md`

## Purpose
Holo is not "a long Codex thread". Holo is an externalized subject-runtime system:
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
1. Subject profile layer
- Public templates:
  - `.subject.example.md`
  - `holo_memory_library/subject_seed.example.md`
  - `holo_memory_library/voice_profile.example.md`
- Private local files, ignored by Git:
  - `.subject.local.md`
  - `holo_memory_library/subject_seed.md`
  - `holo_memory_library/voice_profile.md`

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
2. Host normalizes input and records it as an event, not an automatic reply
3. Memory bridge builds a structured `mind_packet` plus `intent_state` and `action_market`
4. The subject kernel selects one action
5. Stage18 may choose the existing `micro_fast` generation lane for conservative active-thread reflex speech; this happens only after action selection
6. Only the selected speech action enters processor generation
7. Expression budget, silence, or defer are treated as first-class action outcomes
8. Host writes the chosen action and any outbound turn to runtime store
9. Memory bridge writes archive + working/candidate observations
10. Mind Graph incrementally re-syncs the active thread and predictive continuity after each real turn
11. Existing bounded streams update the Stage19 attention frontier for same-thread continuity warmth
12. Stage20 temporal state hydrates same-thread open loops, commitments, deferred intentions, and resume candidates before heavier recall
13. Stage21 promoted policy sediment applies replay-gated soft overlays inside action-market ranking
14. Stage22 may hydrate bounded same-thread world-coupling cues before heavier recall
15. Stage22 canary gate records shadow/live artifacts after action selection and can only block or suppress
16. Background promotion/dream/self-model/drive cycles adjust longer-term memory and future action bias

## Current Runtime Truth
- Main processor: `codex_cli`
- Processor lanes: `kernel_xhigh`, `subject_main`, and `micro_fast`
- Stage18 dual-speed reflex is live: ordinary short active-thread speech can generate through existing `micro_fast`, while explicit memory/history/factual turns still escalate and high-risk actions still use `subject_main` or `kernel_xhigh`
- Stage19 bounded continuity is live: `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle` can warm a bounded Mind Graph `attention_frontier`; ingress reads one same-thread row before heavier recall and exposes `mind_packet.stage19`
- Stage20 temporal continuity is live: Mind Graph `temporal_subject_state` persists open loops, commitments, deferred intentions, interruption markers, resume candidates, and due followup keys; `QueueStore.jobs` remains the timing/job surface and recovery flows through action-market metadata
- Stage21 policy sedimentation is live: Mind Graph `policy_sediment` stores replay-gated, reversible soft overlays; promoted rows can bias action-market scores but cannot grant send permission or override hard policy gates
- Stage22 online canary is live in host-side shadow-first form: `online_canary_traces` and canary artifacts record would-have decisions, `canary_live` requires whitelist/rate/rollback gates, and Mind Graph `world_coupling_signal` hydrates bounded perception cues without creating a new decision layer
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
- `docs/MIND_OS_STAGE5_INTENT_LED_SUBJECT.md`: Stage-5 subject-first runtime design
- `docs/ROADMAP_REGISTRY.md`: preserved primary/secondary/deferred tracks
- `tests/`: regression coverage for host, memory, and Windows helper

## Invariants
- Do not let a transport silently fall back to a different online mode
- Do not store internal prompts, rewrite reasons, or hook control text as user memory
- Do not let fast-path WeChat replies truncate into half-sentences
- Do not let runtime state be the only source of history; archive must remain the durable ledger
- Do not depend on one Codex chat thread to keep Holo alive
- Do not treat `codex_session_id` as memory; it is only a resumable compute cache
- Do not let WeChat single chats split into `wechat:<name>` and `<name>` alias threads
- Do not let Stage18 predictive continuity select actions or bypass explicit memory/history escalation
- Do not let Stage19 attention frontier become a second brain, a new always-on loop, or a transport-side decision layer
- Do not let Stage20 temporal state send directly, duplicate due jobs, override hard policy gates, or bypass explicit memory/history escalation
- Do not let Stage21 policy sediment become hidden training, hard policy, transport-side decision logic, or a send-permission bypass
- Do not let Stage22 canary choose actions, grant send permission, mutate live policy, or let world-coupling cues trigger recall by themselves
- Do not publish live memory JSONL or runtime graph state to a public remote; memory sync belongs only on trusted local/private paths
- Do not publish private subject-profile files; public releases keep only templates and generic docs

## Current Weak Spots
- `pyweixin_dialog` on `Weixin 4.1` is usable but still the most fragile part
- live trigger behavior still needs more real-world hardening
- Stage22 default is `shadow`; a live canary window still needs deliberate enablement and monitoring
- image understanding is still "artifact + sidecar text + metadata first", not a fully native visual stack
- latency still needs more fast-path tuning

## What To Update When You Change Holo
If a thread changes runtime behavior, also update:
- `HOLO_HANDOFF.md`
- `HOLO_SYSTEM.md`
- `HOLO_DEVELOPMENT.md`
- `HOLO_HOST.md`
- `OPERATIONS.md`
- `docs/PUBLIC_RELEASE_HYGIENE.md` when publish boundaries change
- tests covering the changed path
