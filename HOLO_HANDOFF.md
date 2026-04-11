# Holo Handoff

This is the single entrypoint for a new thread that needs to continue Holo work without hidden context.

## Read This First
1. `HOLO_HANDOFF.md`
2. `docs/HANDOFF_CHECKLIST.md`
3. `docs/ROADMAP_REGISTRY.md`
4. `.agent/PLANS.md`
5. `.agent/STAGE23_27_PROGRAM.md`
6. `docs/HOLO_ARCHITECTURE_MAP.md`
7. `docs/WHEEL_CATALOG.md`
8. `docs/PROCESSOR_ROUTING_AND_COST_POLICY.md`
9. `docs/PROVIDER_COMPATIBILITY_CONTRACT.md`
10. `docs/WECHAT_WATCHER_INTERFACE_CONTRACT.md`
11. `docs/STAGE9_INTELLIGENCE_AND_CODEX_COST.md`
12. `docs/ENGINEERING_HANDOFF_STAGE9.md`
13. `docs/STAGE10_ENGINEERING_AWARENESS_AND_CODEX_COST.md`
14. `docs/ENGINEERING_HANDOFF_STAGE10.md`
15. `docs/STAGE12_OUTCOME_CLOSURE_AND_CANONICAL_IDENTITY.md`
16. `docs/ENGINEERING_HANDOFF_STAGE12.md`
17. `docs/STAGE13_EMPIRICAL_ACTION_CALIBRATION.md`
18. `docs/ENGINEERING_HANDOFF_STAGE13.md`
19. `docs/STAGE14_OFFLINE_REPLAY_AND_POLICY_EVAL.md`
20. `docs/ENGINEERING_HANDOFF_STAGE14.md`
21. `docs/STAGE15_KERNEL_MODULARIZATION.md`
22. `docs/ENGINEERING_HANDOFF_STAGE15.md`
23. `docs/STAGE16_RELEASE_HARDENING_AND_ONLINE_SHADOW_LAUNCH.md`
24. `docs/ENGINEERING_HANDOFF_STAGE16.md`
25. `docs/STAGE17_THREAD_RESIDENT_REALTIME_RUNTIME.md`
26. `docs/ENGINEERING_HANDOFF_STAGE17.md`
27. `docs/STAGE18_DUAL_SPEED_REFLEX_AND_PREDICTIVE_CONTINUITY.md`
28. `docs/ENGINEERING_HANDOFF_STAGE18.md`
29. `docs/STAGE19_BOUNDED_BACKGROUND_CONTINUITY_AND_ATTENTION_FRONTIER.md`
30. `docs/ENGINEERING_HANDOFF_STAGE19.md`
31. `docs/STAGE20_TEMPORAL_COMMITMENTS_AND_INTERRUPTION_RECOVERY.md`
32. `docs/ENGINEERING_HANDOFF_STAGE20.md`
33. `docs/STAGE21_POLICY_SEDIMENTATION_AND_NEGOTIATED_WILL.md`
34. `docs/ENGINEERING_HANDOFF_STAGE21.md`
35. `docs/STAGE22_BOUNDED_BLACKBOX_ONLINE_CANARY.md`
36. `docs/ENGINEERING_HANDOFF_STAGE22.md`
37. `docs/STAGE23_KERNEL_SHELL_ORTHOGONALIZATION_AND_RELEASE_PARITY.md`
38. `docs/ENGINEERING_HANDOFF_STAGE23.md`
39. `docs/STAGE24_SCENE_STATE_CONTINUITY_LAYER.md`
40. `docs/ENGINEERING_HANDOFF_STAGE24.md`
41. `docs/STAGE25_DENSE_CONTINUITY_SCHEDULER_AND_WORKING_SET.md`
42. `docs/ENGINEERING_HANDOFF_STAGE25.md`
43. `HOLO_SYSTEM.md`
44. `HOLO_HOST.md`
45. `OPERATIONS.md`
46. `holo_memory_library/MEMORY_LIBRARY.md`
47. `windows_helper/README.md`

## What This Document Must Cover
- current live state
- mandatory reading order
- hard contracts and forbidden edits
- processor routing and cost policy entrypoints
- current next-step focus for the next thread

## What Holo Is
- Holo is not one long Codex conversation.
- Holo is an externalized system:
  - memory is the durable self
  - the processor is replaceable compute
  - transports are eyes and hands
- The current milestone tag is `stage25-dense-continuity-scheduler-and-working-set`.
- The current processor fabric milestone is `processor-fabric-standardized`.
- Current focus is Stage26 replay and promotion gating on top of a green Stage25 dense-continuity baseline. The next arc remains tracked in `.agent/PLANS.md` and `.agent/STAGE23_27_PROGRAM.md`.
- The current subject-runtime arc is:
  - Stage18: dual-speed reflex and predictive continuity inside `ActiveThreadState` is implemented
  - Stage19: bounded background continuity and attention frontier is implemented using only `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`
  - Stage20: temporal commitments and interruption recovery through queue + Mind Graph state is implemented
  - Stage21: reversible policy sedimentation and negotiated will as action-market bias is implemented
  - Stage22: host-side shadow/canary telemetry, live-artifact replay, rollback switch, and bounded world-coupling cues are implemented
  - Stage23: semantic subject results are orthogonalized from delivery/canary suppression, artifact ingest is backward-compatible again, and replay gates consume raw metrics while rounded metrics remain reporting-only
  - Stage24: per-thread `scene_state` is now persisted, inspectable, prompt-visible before verbatim history, and action-market-visible as bounded scene deltas
  - Stage25: bounded dense continuity now keeps a hot-thread working set warm between turns using the existing stream family only, persists `dense_working_set` and `thread_pulse_trace`, and hydrates ingress before heavier recall
- The next planned arc is:
  - Stage26: long-horizon replay and promotion gates
  - Stage27: online long-horizon canary
  - Artifact/tool/outcome progress coupling is deferred beyond the current Stage25 milestone and should not be silently folded into Stage26
  - Bounded subject programs are deferred beyond the current Stage25 dense-continuity milestone
- This arc must not add a second brain, a new unbounded always-on loop, or transport-side decision logic.

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
- Primary provider path: `codex_cli`
- Processor fabric is active with three lanes:
  - `kernel_xhigh`
  - `subject_main`
  - `micro_fast`
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
- Processor routing, provider compatibility, and usage accounting are now first-class runtime surfaces; new threads should inspect them before changing any model call sites.

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
- Processor routing:
  - `python3 -m holo_host show-processor-routing`
- Provider status:
  - `python3 -m holo_host show-provider-status`
- Usage ledger:
  - `python3 -m holo_host show-usage-ledger --limit 50`
- Replay calibration fixture:
  - `python3 -m holo_host replay-calibration-fixture --fixture-path tests/fixtures/stage14`
- Replay policy regret:
  - `python3 -m holo_host replay-policy-regret --fixture-path tests/fixtures/stage14`
- Processor fabric acceptance:
  - `python3 -m holo_host accept-processor-fabric`
- Stage14 acceptance:
  - `python3 -m holo_host accept-stage14`
- Stage18 acceptance:
  - `python3 -m holo_host accept-stage18 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Stage19 acceptance:
  - `python3 -m holo_host accept-stage19 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Stage19 frontier diagnostics:
  - `python3 -m holo_host show-attention-frontier --channel wechat`
  - `python3 -m holo_host trace-wake-reasons --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
  - `python3 -m holo_host show-thread-warmth --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Stage20 temporal diagnostics:
  - `python3 -m holo_host show-open-loops --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
  - `python3 -m holo_host show-commitments --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
  - `python3 -m holo_host trace-resume-candidate --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Stage21 policy sediment diagnostics:
  - `python3 -m holo_host show-policy-candidates --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
  - `python3 -m holo_host show-promoted-policies --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
  - `python3 -m holo_host trace-policy-influence --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "continue this carefully"`
  - `python3 -m holo_host rollback-policy --id <policy_id>`
- Stage22 online canary diagnostics:
  - `python3 -m holo_host show-online-canary`
  - `python3 -m holo_host show-blackbox-metrics --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
  - `python3 -m holo_host trace-canary-decision --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "still here?"`
  - `python3 -m holo_host set-canary-rollback --enabled true --reason manual_hold`
  - `python3 -m holo_host replay-live-artifacts --since-hours 24`
  - `python3 -m holo_host show-world-coupling --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Stage23 release-parity acceptance:
  - `python3 -m holo_host accept-stage23 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Stage24 scene-state continuity acceptance:
  - `python3 -m holo_host accept-stage24 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Stage25 dense continuity diagnostics:
  - `python3 -m holo_host show-continuity-budget --channel wechat`
  - `python3 -m holo_host show-dense-working-set --channel wechat`
  - `python3 -m holo_host trace-thread-pulse --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Stage25 dense continuity acceptance:
  - `python3 -m holo_host accept-stage25 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Stage15 replay-preserving refactor tests:
  - `pytest -q tests/test_stage15_modularization.py`

## When A New Thread Starts Work
1. Read the docs above in order.
2. Run `./scripts/holo-status.sh`.
3. Run `python3 -m holo_host show-provider-status`.
4. Run `python3 -m holo_host show-processor-routing`.
5. Check whether Holo is supposed to stay online before touching runtime files.
6. Run targeted tests before editing.
7. Make one focused change.
8. Re-run relevant tests.
9. Update docs if runtime behavior, memory semantics, provider routing, or operator workflow changed.

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
- Processor routing and cost:
  - `python3 -m holo_host show-processor-routing`
  - `python3 -m holo_host show-provider-status`
  - `python3 -m holo_host show-usage-ledger --limit 100`

## Current Weak Spots
- `reply_api.py` is still a large facade even after Stage23 orthogonalized semantic and delivery concerns; further structural slimming should happen only behind replay and acceptance coverage
- `pyweixin_dialog` on `Weixin 4.1` is still the most fragile live layer
- live WeChat trigger behavior still needs real-world hardening
- image understanding is still artifact-first, not a fully native visual stack
- latency and fast-path tuning still need work
- cache reuse is still cold in practice
- proactive initiative exists but is often blocked by `initiative_probe_blocked`
- retrieval and expression control still feel more engineered than natural
- main-brain override and initiative gate calibration can create false negatives under cold `initiative_window` states
- token accounting now exists, but some providers still rely on estimates rather than ground-truth usage
- provider fallback behavior is standardized, but fallback paths still need more live soak time
- replay coverage is now deterministic, but fixture breadth is still narrow and should grow only when it exposes a real blind spot
- Stage15 helper-module extraction is in place, but facade files are still larger than ideal and should only be slimmed further behind replay checks

- Stage18 `micro_fast` routing is intentionally conservative; do not broaden it without proving explicit memory/history escalation and action-market-first still hold
- Stage20 temporal state is intentionally bounded and inspectable; do not let it create direct sends, unbounded scheduling, or a second decision layer
- Stage21 policy sediment is intentionally replay-gated and reversible; do not let it become a hard policy override, learned hidden weights, or send-permission bypass
- Stage22 canary is host-side and shadow-first; do not let it pick actions, grant send permission, hide metrics, or turn world-coupling cues into a recall trigger
- Stage25 dense continuity is intentionally bounded and stream-driven; do not let it trigger heavy recall, create a new loop family, or become a watcher-side decision layer

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
- `python3 -m holo_host accept-stage12 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host accept-stage13 --thread-key wechat:Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host accept-stage14`
- `python3 -m holo_host accept-stage17 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-processor-routing`
- `python3 -m holo_host show-provider-status`
- `python3 -m holo_host accept-stage8 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`

## Implemented Subject-Runtime Arc Commands
- `python3 -m holo_host accept-stage18 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-fast-path-metrics --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-predictive-continuity --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host trace-reflex-routing --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "still here?"`
- `python3 -m holo_host accept-stage19 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-attention-frontier --channel wechat`
- `python3 -m holo_host trace-wake-reasons --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-thread-warmth --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host accept-stage20 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-open-loops --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-commitments --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host trace-resume-candidate --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host accept-stage21 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-policy-candidates --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-promoted-policies --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host trace-policy-influence --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "continue this carefully"`
- `python3 -m holo_host rollback-policy --id <policy_id>`
- `python3 -m holo_host accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host accept-stage23 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host show-online-canary`
- `python3 -m holo_host show-blackbox-metrics --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python3 -m holo_host trace-canary-decision --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "still here?"`
- `python3 -m holo_host replay-live-artifacts --since-hours 24`
- `python3 -m holo_host show-world-coupling --thread-key Nemoqi --chat-name Nemoqi --channel wechat`

## Next Arc Program
- Durable Stage23-27 sources of truth:
  - `.agent/PLANS.md`
  - `.agent/STAGE23_27_PROGRAM.md`
- Default sequencing:
  - Stage24 is implemented as the scene-state continuity layer
  - Stage25 couples artifact, tool, and outcome progress into the same bounded scene-state surface
  - Stage26 extends replay discipline and promotion gates to longer-horizon behavior
  - Stage27 canaries longer-horizon behavior online in host-side shadow-first mode
  - Bounded subject programs are deferred until a later explicit re-plan
- Current verified baseline after Stage24:
  - `pytest -q` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed on `2026-04-11`

## Invariants
- Do not silently change online transport modes
- Do not touch the watcher path without reading `docs/WECHAT_WATCHER_INTERFACE_CONTRACT.md`
- Do not add new direct model call paths outside the processor provider abstraction
- Do not bypass lane routing by hardcoding `codex exec` or raw HTTP calls in random modules
- Do not let internal prompts, hook control text, or rewrite reasons enter durable memory
- Do not let archive be the only place history lives, but also do not let runtime threads become the only continuity
- Do not depend on one Codex thread to keep Holo alive
- Do not forget to keep CLI archive hooks working when editing repo-local hook config
- Do not treat `autobiographical_state`, `goal_state`, or `world_state` as display-only metadata; they are now part of subject deliberation
- Do not publish live memory or runtime state to the public repo
- Do not treat `show-processor-routing`, `show-provider-status`, or `show-usage-ledger` as optional maintenance extras; they are required observability for safe handoff
- Do not enable `canary_live` or restart live services as part of a normal Stage22 code push

## Minimum Done For Any Holo Change
- local behavior works
- tests pass
- state is observable
- docs are updated
- when Stage23-27 planning or runtime sequencing changes, update `.agent/PLANS.md`, `.agent/STAGE23_27_PROGRAM.md`, `HOLO_HANDOFF.md`, and `docs/ROADMAP_REGISTRY.md` together
- another thread can continue from disk without hidden oral context
- when `accept-stage9` is available, run it before and after any gate-mode transition
- when model routing, provider fallback, or token policy changes, run `accept-processor-fabric`
- when calibration or policy quality changes, rerun `accept-stage14` and inspect replay artifacts
