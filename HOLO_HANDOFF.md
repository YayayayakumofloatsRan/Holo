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
43. `docs/STAGE26_BOUNDED_TASK_WORLD_STATE.md`
44. `docs/ENGINEERING_HANDOFF_STAGE26.md`
45. `docs/STAGE27_LONG_HORIZON_REPLAY_AND_PROMOTION_GATES.md`
46. `docs/ENGINEERING_HANDOFF_STAGE27.md`
47. `docs/STAGE28_MULTIMODAL_HOMEOSTATIC_KERNEL.md`
48. `docs/ENGINEERING_HANDOFF_STAGE28.md`
49. `docs/STAGE29_BIONIC_SUBJECT_KERNEL.md`
50. `docs/ENGINEERING_HANDOFF_STAGE29.md`
51. `docs/STAGE30_UNIFIED_SUBJECT_LOOP.md`
52. `docs/ENGINEERING_HANDOFF_STAGE30.md`
53. `docs/STAGE31_DEBT_BURNDOWN_AND_DIAGNOSTICS.md`
54. `docs/ENGINEERING_HANDOFF_STAGE31.md`
55. `docs/STAGE32_RESPONSE_SHAPING_AND_TEMPLATE_PRESSURE.md`
56. `docs/ENGINEERING_HANDOFF_STAGE32.md`
57. `docs/STAGE33_PROVIDER_API_CONTRACTS.md`
58. `docs/ENGINEERING_HANDOFF_STAGE33.md`
59. `docs/STAGE34_DEBT_REGISTRY_AND_VISUAL_READINESS.md`
60. `docs/ENGINEERING_HANDOFF_STAGE34.md`
61. `docs/STAGE35_INTERNAL_RUNTIME_READINESS.md`
62. `docs/ENGINEERING_HANDOFF_STAGE35.md`
63. `docs/STAGE36_AUTONOMOUS_INQUIRY_QUALITY.md`
64. `docs/ENGINEERING_HANDOFF_STAGE36.md`
65. `docs/STAGE37_BIONIC_SELF_EVAL_AND_CAPABILITY_HONESTY.md`
66. `docs/ENGINEERING_HANDOFF_STAGE37.md`
67. `docs/STAGE38_VISUAL_PROVIDER_BRIDGE.md`
68. `docs/ENGINEERING_HANDOFF_STAGE38.md`
69. `docs/STAGE39_BIONIC_TURING_BENCHMARK.md`
70. `docs/ENGINEERING_HANDOFF_STAGE39.md`
71. `HOLO_SYSTEM.md`
72. `HOLO_HOST.md`
73. `OPERATIONS.md`
74. `docs/PUBLIC_RELEASE_HYGIENE.md`
75. `holo_memory_library/MEMORY_LIBRARY.md`
76. `windows_helper/README.md`

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
- The current milestone tag is `stage39-bionic-turing-benchmark`.
- The current processor fabric milestone is `processor-fabric-standardized`.
- Current focus is post-Stage39 targeted debt repair: provider latency/provider-response caching, replay-backed facade slimming, replay-fixture breadth from concrete regressions, or operator-approved live WeChat hardening. Holo remains internal-only unless a separate operator-approved live transport plan says otherwise.
- The current subject-runtime arc is:
  - Stage18: dual-speed reflex and predictive continuity inside `ActiveThreadState` is implemented
  - Stage19: bounded background continuity and attention frontier is implemented using only `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`
  - Stage20: temporal commitments and interruption recovery through queue + Mind Graph state is implemented
  - Stage21: reversible policy sedimentation and negotiated will as action-market bias is implemented
  - Stage22: host-side shadow/canary telemetry, live-artifact replay, rollback switch, and bounded world-coupling cues are implemented
  - Stage23: semantic subject results are orthogonalized from delivery/canary suppression, artifact ingest is backward-compatible again, and replay gates consume raw metrics while rounded metrics remain reporting-only
  - Stage24: per-thread `scene_state` is now persisted, inspectable, prompt-visible before verbatim history, and action-market-visible as bounded scene deltas
  - Stage25: bounded dense continuity now keeps a hot-thread working set warm between turns using the existing stream family only, persists `dense_working_set` and `thread_pulse_trace`, and hydrates ingress before heavier recall
  - Stage26: bounded `task_world_object` plus `task_world_link` now persist inspectable task-world state, link temporal commitments and same-thread world objects explicitly, and hydrate same-thread ingress before heavier recall while Stage22 `world_coupling_signal` remains a compatibility projection
  - Stage27: observational long-horizon blackbox soak, scorecards, replay-on-live-artifacts, and blind evaluation export are implemented as operational-only surfaces
  - Stage28: multimodal situational fields now fuse visual memory, scene state, dense continuity, task-world state, temporal pressure, and homeostatic pressure before prompt history, with inspectable action-market deltas
  - Stage29: a unified bionic subject kernel, CLI adapter, synthetic WeChat adapter validation, operational trace persistence, bionic metrics, trace export, and DeepSeek provider compatibility are implemented without starting WeChat or mutating self-memory
  - Stage30: an explicit unified `subject_loop` contract is visible over the bionic capsule, with hard invariants from perception through state update
  - Stage31: adapter registry, controlled state-update gate, subject-loop trace/metrics diagnostics, and bionic CLI helper extraction are implemented as offline debt burn-down
  - Stage32: deterministic fallback response shaping replaces the fixed fallback template, exposes `shape` and `context_refs`, and adds `context_shaping_score`
  - Stage33: provider API contracts are inspectable, `openai_compatible` uses chat-completions, and processor-fabric-only model-call boundaries remain explicit
  - Stage34: current technical debt is classified in `holo_host/debt_registry.py`, visual-provider readiness is inspectable without live calls, and `accept-stage34` prevents hidden weak spots or image-capability overclaiming
  - Stage35: internal DeepSeek runtime readiness is machine-checkable, local config is secret-scanned, env-key presence is redacted, and the gate verifies WeChat transport has not been started
  - Stage36: autonomous inquiry formatting debt is closed in the offline bionic kernel; deterministic fallback asks at most one grounded question, exposes inquiry-quality metrics, and preserves action-market-first generation without starting WeChat
  - Stage37: internal bionic self-evaluation now guards provider-backed generation against empty-continuity hallucination, text-provider image overclaiming, excessive question/markdown pressure, and non-speech CLI self-eval empty replies
  - Stage38: explicit bionic CLI image input now routes through `image_understand`, stores image-capable provider metadata in visual memory, and grounds text-only generation in visual summaries without claiming direct raw image access
  - Stage39: internal bionic Turing scoring now gates CLI continuity, naturalness, mechanism-leakage prevention, question bounds, and context grounding
- Post-Stage39 cache diagnostics: exact packet-cache reuse is confirmed live; cache-class homeostasis deficits now require enough packet-cache observations and are rebased from live cache stats instead of stale self-model metadata.
- The next planned arc is:
  - Stage40+: explicit re-plan for provider latency/provider-response caching, replay-backed facade slimming, replay-fixture breadth, or operator-approved live transport hardening
  - Online long-horizon canary remains deferred beyond Stage28 and must stay replay-first, whitelist-only, rollback-safe, and explicitly re-planned
  - Artifact/tool/outcome progress coupling remains deferred and should not be silently folded into Stage28 or a future canary
  - Bounded subject programs remain deferred beyond the current Stage28 milestone
- This arc must not add a second brain, a new unbounded always-on loop, or transport-side decision logic.

## Source Of Truth
- Public subject-profile templates:
  - `.subject.example.md`
  - `holo_memory_library/subject_seed.example.md`
  - `holo_memory_library/voice_profile.example.md`
- Private local subject-profile files, ignored by Git:
  - `.subject.local.md`
  - `holo_memory_library/subject_seed.md`
  - `holo_memory_library/voice_profile.md`
- Runtime kernel:
  - `holo_host/`
- Long-term and working memory tooling:
  - `holo_memory_library/`
- Private live memory stores, ignored by Git:
  - `holo_memory_library/memories/*.jsonl`
- Operations and recovery:
  - `scripts/`
  - `OPERATIONS.md`
- Windows transport shell:
  - `windows_helper/`

## Current Runtime Truth
- Public/example provider path: `codex_cli`
- Internal local provider path: `deepseek` through the processor fabric when `.holo_host.toml` and `DEEPSEEK_API_KEY` are configured
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
- Full turn archive file, private/local only:
  - `holo_memory_library/memories/conversation_archive.jsonl`
- CLI conversations are also archived when repo-local Codex hooks are active:
  - `/.codex/hooks.json`
  - `holo_memory_library/codex_hooks/user_prompt_submit.py`
  - `holo_memory_library/codex_hooks/stop_revise.py`
- Quick check for recent CLI archive rows:
  - `python3 holo_memory_library/rag_memory.py show-archive --channel codex_cli --limit 5`

## Mutable Runtime State
These files change while Holo is alive. Do not treat them like static docs, and do not publish them.
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
- Provider contracts:
  - `python3 -m holo_host show-provider-contracts`
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
  - `python3 -m holo_host accept-stage18 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage19 acceptance:
  - `python3 -m holo_host accept-stage19 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage19 frontier diagnostics:
  - `python3 -m holo_host show-attention-frontier --channel wechat`
  - `python3 -m holo_host trace-wake-reasons --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host show-thread-warmth --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage20 temporal diagnostics:
  - `python3 -m holo_host show-open-loops --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host show-commitments --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host trace-resume-candidate --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage21 policy sediment diagnostics:
  - `python3 -m holo_host show-policy-candidates --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host show-promoted-policies --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host trace-policy-influence --thread-key TestUser --chat-name TestUser --channel wechat --query "continue this carefully"`
  - `python3 -m holo_host rollback-policy --id <policy_id>`
- Stage22 online canary diagnostics:
  - `python3 -m holo_host show-online-canary`
  - `python3 -m holo_host show-blackbox-metrics --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host show-blackbox-scorecard --since-hours 168`
  - `python3 -m holo_host trace-canary-decision --thread-key TestUser --chat-name TestUser --channel wechat --query "still here?"`
  - `python3 -m holo_host set-canary-rollback --enabled true --reason manual_hold`
  - `python3 -m holo_host replay-live-artifacts --since-hours 24`
  - `python3 -m holo_host export-blind-packets --since-hours 168`
  - `python3 -m holo_host run-blackbox-soak --since-hours 168`
  - `python3 -m holo_host show-world-coupling --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage23 release-parity acceptance:
  - `python3 -m holo_host accept-stage23 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage24 scene-state continuity acceptance:
  - `python3 -m holo_host accept-stage24 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage25 dense continuity diagnostics:
  - `python3 -m holo_host show-continuity-budget --channel wechat`
  - `python3 -m holo_host show-dense-working-set --channel wechat`
  - `python3 -m holo_host trace-thread-pulse --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage25 dense continuity acceptance:
  - `python3 -m holo_host accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage26 task-world diagnostics:
  - `python3 -m holo_host show-task-world --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host trace-world-object --object-id <object_id>`
  - `python3 -m holo_host trace-thread-object-links --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage26 task-world acceptance:
  - `python3 -m holo_host accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage27 long-horizon soak acceptance:
  - `python3 -m holo_host accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage28 multimodal situational diagnostics:
  - `python3 -m holo_host show-situational-field --thread-key TestUser --chat-name TestUser --channel wechat --query "continue"`
  - `python3 -m holo_host trace-visual-field --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host trace-inquiry-shaping --thread-key TestUser --chat-name TestUser --channel wechat --query "continue"`
- Stage28 multimodal kernel acceptance:
  - `python3 -m holo_host accept-stage28 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage29 bionic subject-kernel diagnostics:
  - `python3 -m holo_host agent-run --query "continue" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
  - `python3 -m holo_host show-bionic-metrics`
  - `python3 -m holo_host agent-trace --trace-id <trace_id>`
- Stage29 bionic subject-kernel acceptance:
  - `python3 -m holo_host accept-stage29 --thread-key TestUser --chat-name TestUser --channel cli`
- Stage30 unified subject-loop acceptance:
  - `python3 -m holo_host accept-stage30 --thread-key TestUser --chat-name TestUser --channel cli`
- Stage31 debt burn-down diagnostics:
  - `python3 -m holo_host trace-subject-loop --trace-id <trace_id>`
  - `python3 -m holo_host show-subject-loop-metrics`
- Stage31 debt burn-down acceptance:
  - `python3 -m holo_host accept-stage31 --thread-key TestUser --chat-name TestUser --channel cli`
- Stage32 response-shaping acceptance:
  - `python3 -m holo_host accept-stage32 --thread-key TestUser --chat-name TestUser --channel cli`
- Stage33 provider API contract acceptance:
  - `python3 -m holo_host accept-stage33`
- Stage34 debt registry and visual-readiness diagnostics:
  - `python3 -m holo_host show-debt-registry`
  - `python3 -m holo_host show-visual-provider-readiness`
- Stage34 debt registry and visual-readiness acceptance:
  - `python3 -m holo_host accept-stage34`
- Stage35 internal runtime readiness diagnostics:
  - `python3 -m holo_host show-internal-runtime-readiness`
- Stage35 internal runtime readiness acceptance:
  - `python3 -m holo_host accept-stage35`
- Stage36 autonomous inquiry quality acceptance:
  - `python3 -m holo_host accept-stage36 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage37 bionic self-eval and capability-honesty acceptance:
  - `python3 -m holo_host accept-stage37 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage38 visual-provider bridge acceptance:
  - `python3 -m holo_host accept-stage38 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage39 bionic Turing benchmark:
  - `python3 -m holo_host show-bionic-turing-scorecard --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage39 bionic Turing benchmark acceptance:
  - `python3 -m holo_host accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli`
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
  - `python3 -m holo_host show-provider-contracts`
  - `python3 -m holo_host show-visual-provider-readiness`
  - `python3 -m holo_host show-debt-registry`
  - `python3 -m holo_host show-internal-runtime-readiness`
  - `python3 -m holo_host show-bionic-turing-scorecard --thread-key cli:TestUser --chat-name TestUser --channel cli`
  - `python3 -m holo_host show-usage-ledger --limit 100`

## Current Weak Spots
- Canonical classification now lives in `python3 -m holo_host show-debt-registry`; do not delete or soften weak spots without updating that registry and the latest acceptance gate.
- Internal DeepSeek runtime readiness now lives in `python3 -m holo_host show-internal-runtime-readiness`; do not claim Holo is internally runnable until it passes.
- Autonomous inquiry formatting debt is now bounded by `python3 -m holo_host accept-stage36`; do not reintroduce label-template inquiry or multiple ungrounded questions.
- Bionic self-evaluation and capability honesty are now bounded by `python3 -m holo_host accept-stage37`; do not let provider-backed CLI replies invent missing continuity, overclaim image ability, or return empty text for self-eval probes.
- Internal visual-provider bridging is now bounded by `python3 -m holo_host accept-stage38`; explicit CLI images must go through `image_understand`, and text-only generation may describe only visual-memory summaries.
- Internal bionic Turing quality is now bounded by `python3 -m holo_host accept-stage39`; do not let ordinary CLI replies expose internal machinery, reset continuity, or pass scores through formulaic/theatrical phrasing.
- `reply_api.py` remains bounded structural debt. Further slimming must happen only behind dedicated compatibility tests, replay checks, and acceptance gates.
- `pyweixin_dialog`, live WeChat trigger behavior, latency/cache/provider-fallback soak, and live visual-provider soak are external-precondition debts while Holo remains WeChat-offline.
- Visual-provider readiness is now bounded by `show-visual-provider-readiness` plus `accept-stage38`: text APIs must not overclaim image support, and explicit CLI image input must preserve image-capable provider metadata.
- Replay fixture breadth remains intentionally narrow and should grow only when it exposes a real blind spot.
- Stage15 helper-module extraction is in place, but facade files are still larger than ideal and should only be slimmed further behind replay checks.

- Stage18 `micro_fast` routing is intentionally conservative; do not broaden it without proving explicit memory/history escalation and action-market-first still hold
- Stage20 temporal state is intentionally bounded and inspectable; do not let it create direct sends, unbounded scheduling, or a second decision layer
- Stage21 policy sediment is intentionally replay-gated and reversible; do not let it become a hard policy override, learned hidden weights, or send-permission bypass
- Stage22 canary is host-side and shadow-first; do not let it pick actions, grant send permission, hide metrics, or turn world-coupling cues into a recall trigger
- Stage25 dense continuity is intentionally bounded and stream-driven; do not let it trigger heavy recall, create a new loop family, or become a watcher-side decision layer
- Stage26 task-world state is intentionally bounded and same-thread-first; do not let it become a second decision layer, a cross-thread hidden coupling path, or a heavy-recall trigger

## Stage-9 Focus
- goal: remove over-conservative proactive gating while preserving hard safety constraints
- hard_gate: non-overridable constraints such as whitelist policy, cooldown, per-thread allow flag, policy decision, and explicit disable
- soft_gate: `trust`, `initiative_window`, `drive_pressure`, `pressure_level` become directional scoring inputs
- main_brain_override: allowed only when gate is soft-blocked and mode is healthy; never bypasses hard_gate
- rollout: begin in `initiative_gate_mode=conservative`, verify, then switch default to adaptive

## Stage-9 Entry Commands
- `python3 -m holo_host initiative-probe --thread-key TestUser --chat-name TestUser`
- `python3 -m holo_host show-initiative-status --thread-key TestUser --chat-name TestUser`
- `python3 -m holo_host accept-stage9 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage12 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage13 --thread-key wechat:TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage14`
- `python3 -m holo_host accept-stage17 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-processor-routing`
- `python3 -m holo_host show-provider-status`
- `python3 -m holo_host accept-stage8 --thread-key TestUser --chat-name TestUser --channel wechat`

## Implemented Subject-Runtime Arc Commands
- `python3 -m holo_host accept-stage18 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-fast-path-metrics --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-predictive-continuity --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-reflex-routing --thread-key TestUser --chat-name TestUser --channel wechat --query "still here?"`
- `python3 -m holo_host accept-stage19 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-attention-frontier --channel wechat`
- `python3 -m holo_host trace-wake-reasons --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-thread-warmth --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage20 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-open-loops --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-commitments --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-resume-candidate --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage21 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-policy-candidates --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-promoted-policies --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-policy-influence --thread-key TestUser --chat-name TestUser --channel wechat --query "continue this carefully"`
- `python3 -m holo_host rollback-policy --id <policy_id>`
- `python3 -m holo_host accept-stage22 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage23 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-online-canary`
- `python3 -m holo_host show-blackbox-metrics --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-blackbox-scorecard --since-hours 168`
- `python3 -m holo_host trace-canary-decision --thread-key TestUser --chat-name TestUser --channel wechat --query "still here?"`
- `python3 -m holo_host replay-live-artifacts --since-hours 24`
- `python3 -m holo_host export-blind-packets --since-hours 168`
- `python3 -m holo_host run-blackbox-soak --since-hours 168`
- `python3 -m holo_host show-world-coupling --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage24 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-scene-state --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-scene-compression --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-dense-working-set --channel wechat`
- `python3 -m holo_host trace-thread-pulse --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-task-world --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-world-object --object-id <object_id>`
- `python3 -m holo_host trace-thread-object-links --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host agent-run --query "continue" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
- `python3 -m holo_host show-bionic-metrics`
- `python3 -m holo_host show-subject-loop-metrics`
- `python3 -m holo_host show-provider-contracts`
- `python3 -m holo_host show-visual-provider-readiness`
- `python3 -m holo_host show-debt-registry`
- `python3 -m holo_host accept-stage29 --thread-key TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage30 --thread-key TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage31 --thread-key TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage32 --thread-key TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage33`
- `python3 -m holo_host accept-stage34`
- `python3 -m holo_host show-internal-runtime-readiness`
- `python3 -m holo_host accept-stage35`
- `python3 -m holo_host accept-stage36 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage37 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage38 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli`

## Next Arc Program
- Durable Stage23-27 sources of truth:
  - `.agent/PLANS.md`
  - `.agent/STAGE23_27_PROGRAM.md`
- Default sequencing:
  - Stage24 is implemented as the scene-state continuity layer
  - Stage25 is implemented as the dense continuity scheduler and working set
  - Stage26 is implemented as bounded task-world state
  - Stage27 is implemented as the observational long-horizon blackbox soak, scorecard, blind review export, and replay-first follow-up eligibility reporting layer
  - Stage28 is implemented as the multimodal homeostatic kernel over visual memory, scene state, dense continuity, and task-world state
  - Stage29 is implemented as the bionic subject kernel with CLI as first adapter
  - Stage30 is implemented as the unified subject-loop contract
  - Stage31 is implemented as debt burn-down and diagnostics
  - Stage32 is implemented as response shaping and template-pressure reduction
  - Stage33 is implemented as provider API contract hardening
  - Stage34 is implemented as debt registry and visual-readiness hardening
  - Stage35 is implemented as internal DeepSeek runtime readiness
  - Stage36 is implemented as autonomous inquiry quality hardening
  - Stage37 is implemented as bionic self-eval and capability-honesty hardening
  - Stage38 is implemented as the internal visual-provider bridge
  - Stage39 is implemented as the internal bionic Turing benchmark
  - Online long-horizon canary remains deferred beyond Stage28
  - Bounded subject programs remain deferred until a later explicit re-plan
- Current verified baseline after Stage39:
  - `pytest -q` passed on `2026-04-11` for the Stage23-27 baseline
  - `pytest -q tests/test_stage28_multimodal_homeostatic_kernel.py` passed on `2026-04-28`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage28 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-28`
  - `pytest -q` passed with `301` tests on `2026-05-10` before Stage39
  - `python -m holo_host --config .holo_host.toml accept-stage36 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-09`
  - `python -m holo_host --config .holo_host.toml accept-stage37 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-09`
  - `python -m holo_host --config .holo_host.toml accept-stage38 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10`
  - `pytest -q tests/test_stage39_bionic_turing_benchmark.py tests/test_stage38_visual_provider_bridge.py tests/test_stage37_bionic_self_eval.py tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml show-bionic-turing-scorecard --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10`
  - `pytest -q` passed with `306` tests on `2026-05-10` after Stage39
  - `python scripts/check_public_release_hygiene.py` passed on `2026-05-10`
  - `git diff --check` reported no whitespace errors on `2026-05-10`
  - Stage29 through Stage39 are offline/internal bionic-kernel/provider/runtime-readiness/inquiry-quality/capability-honesty/visual-provider/bionic-Turing milestones; run the local verification commands in the Stage39 handoff before claiming current green status

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
- Do not publish private subject-profile files; only `.example` templates belong in Git
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
