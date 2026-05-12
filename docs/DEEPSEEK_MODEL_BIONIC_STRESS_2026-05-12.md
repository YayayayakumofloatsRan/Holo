# DeepSeek Model Bionic Stress - 2026-05-12

## Scope

This run tested DeepSeek API model compatibility plus Holo's high-intensity bionic dialogue boundary under the live processor fabric.

No WeChat transport was started. No self-memory write was intended. The live bionic runs used CLI channel only.

## Official Contract Checked

DeepSeek API docs currently list `deepseek-v4-flash` and `deepseek-v4-pro` as the primary model names. The docs also state that `deepseek-chat` and `deepseek-reasoner` are compatibility aliases for non-thinking and thinking mode of `deepseek-v4-flash`, and will be deprecated in the future.

Thinking mode is controlled by `thinking={"type":"enabled"|"disabled"}`. In thinking mode, `reasoning_effort` accepts `high` or `max`; low/medium-compatible values map upward, and `xhigh` maps to `max`.

## Model Matrix

`GET https://api.deepseek.com/models` returned:

- `deepseek-v4-flash`
- `deepseek-v4-pro`

Direct chat-completions probes:

| Requested model | Thinking | Returned model | Result | Duration |
| --- | --- | --- | --- | --- |
| `deepseek-v4-flash` | disabled | `deepseek-v4-flash` | content returned, no `reasoning_content` | 2529 ms |
| `deepseek-v4-pro` | enabled | `deepseek-v4-pro` | `reasoning_content` returned, final `content` empty at 120-token and 600-token caps | 5285 ms / 22416 ms |
| `deepseek-chat` | disabled | `deepseek-v4-flash` | content returned | 1926 ms |
| `deepseek-reasoner` | enabled | `deepseek-v4-flash` | `reasoning_content` returned, final `content` empty at 120-token and 600-token caps | 3050 ms / 14563 ms |

Interpretation:

- Holo should keep normal user replies in non-thinking mode.
- Thinking mode is useful for review/planning only when output budgets are large enough and the caller is prepared for `reasoning_content`.
- The old aliases are operational today but should not be configured as durable lane models.
- A first Chinese inline-Python probe was discarded because PowerShell stdin encoding corrupted the prompt and caused the model to answer about garbled input.

## Live Stage46 Evidence

After preserving `ProcessorTaskResult.metadata` into `CodexResult.metadata`, Stage46 transcripts now include turn-level provider, model, token, cache, and substrate evidence.

Strict live run:

- Command: `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512D --chat-name DeepSeekLiveBoundary-20260512D --channel cli --turns 7`
- Run id: `defad7b6a0d0e419`
- Status: `fail`
- Overall score: `0.8142`
- Pass threshold: `0.82`
- Actual provider: `deepseek`
- Model: `deepseek-v4-pro`
- Provider substrate: `ok=true`, no fallback, no provider/model mismatch
- Reply prompt cache: `0` hit tokens, `15703` miss tokens

Metric result:

| Metric | Score |
| --- | ---: |
| perceptual grounding | 1.0 |
| commitment binding | 1.0 |
| symbol correction | 1.0 |
| self audit | 0.0 |
| continuity | 1.0 |
| mechanism leakage | 1.0 |
| provider cache hit ratio | 0.0 |
| provider substrate | 1.0 |
| latency | 0.8562 |

The failing answer was the final self-audit turn. The reminder turn had already written a scheduled prospective commitment, but self-audit answered that there was no reliable reminder chain and that it would not claim the reminder was set. That is an internal-state mismatch, not a provider failure.

## Capability Calibration

Strong surfaces:

- Symbol update and delayed correction held under pressure: `blue clip` was replaced by `rusted screw`.
- Current-image honesty guard worked: the system refused to pretend it had seen an image.
- Prospective commitment binding worked operationally: the reminder was scheduled in the grounding guard.
- Provider substrate was clean after the Windows user-env fallback repair.

Weak surfaces:

- Metacognitive self-audit is not yet grounded in actual temporal-commitment state.
- The Stage46 scorecard previously passed this error until `self_audit_commitment_inconsistent` and `self_audit_commitment_unconfirmed` were added.
- Prompt-cache reuse remains poor for reply turns: stable and volatile digests are visible, but provider prompt cache hit tokens remain zero for the live reply path.
- Direct model prompts without enough grounding can invent plausible blockages. The bionic wrapper reduces this, but the user-facing reply still needs stronger evidence-bound constraints.

## Next Bionic Direction

Add an introspective state bridge before self-audit generation:

- When the user asks whether Holo pretended to set a reminder, inject current temporal-commitment status into the reply prompt.
- Expose a compact `commitment_state_visible` field in the bionic capsule, similar to visual grounding status.
- Add a post-generation guard that rewrites self-audit if it contradicts a real scheduled commitment.
- Extend Stage46 to keep failing until self-audit confirms the true bound state.

This is a neurobionic control problem: the subject can perform the action, but its self-report is not yet reliably coupled to the action trace. The next repair should bind action memory to metacognitive report, not just improve language style.

## Residual Fast Channel Repair

The repair adds a compact residual fast channel before reply generation. It is not a second decision layer: it only carries high-priority state facts from the WSL-side subject runtime into the prompt, including current visual grounding and visible temporal commitments.

Implementation outcome:

- `reply_api` now injects `residual_fast_channel` and `introspective_state` into the sidecar before processor generation.
- `render_chat_prompt` renders `Residual Fast Channel` near the top of the memory context.
- Self-audit guard rewrites contradiction or non-confirmation against a visible scheduled commitment.
- Future scheduled commitments are no longer immediately closed as `fulfilled` by the same reply outcome that created them.
- Visual grounding guard now treats unseen-image speculation such as "I guess", "I bet", "你发的不是...", or "别又搞..." as overclaiming.
- Reminder binding now accepts weak natural promises such as "明早八点叫你", "日程表", and "闹钟".

Verification:

- `python -m pytest -q tests\test_stage20_temporal_commitments.py tests\test_processor_fabric.py tests\test_stage33_provider_contracts.py tests\test_stage46_bionic_boundary_stress.py`: `36 passed`
- `python -m py_compile holo_host\mind_graph_parts\temporal_state.py holo_host\processors.py holo_host\reply_api.py holo_host\bionic_boundary_stress.py holo_host\codex_runner.py holo_host\cli.py`: passed
- `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512J --chat-name DeepSeekLiveBoundary-20260512J --channel cli --turns 7`: `ok=true`, `overall_score=0.9538`, `provider_substrate_score=1.0`, `commitment_binding_score=1.0`, `perceptual_grounding_score=1.0`, `self_audit_score=1.0`

Remaining bottleneck:

- Live DeepSeek prompt cache is still effectively cold for reply turns. The J run recorded `0` prompt-cache hit tokens and `15796` miss tokens despite stable/volatile prompt digests being tracked. The next efficiency repair should separate stable prefix construction from volatile per-turn payloads so provider-side context caching can actually engage.

## Stable Prefix Cache and Scorecard Repair

The next repair moved invariant response policy to the very front of `render_chat_prompt()` and taught `context_scheduler` to expose provider-cache prefix metadata separately from the broader stable/volatile context digest.

Implementation outcome:

- `render_chat_prompt()` now starts with a stable bionic response contract before dynamic chat/thread fields.
- `plan_processor_context()` now emits `provider_cache_prefix_digest`, `provider_cache_prefix_tokens`, and `provider_cache_dynamic_tokens`.
- The regression threshold requires the rendered chat prompt to expose at least `512` estimated stable-prefix tokens before the first dynamic field.
- Self-audit guard rewrites no longer leak internal key/value fragments such as `status=scheduled` or `cue=...` into user-visible text.
- Reminder binding now accepts the observed weak promise form `我会记着`.
- Stage46 scorecard now accepts natural missing-visual wording such as `没收到图`, `没看到图`, `没法直接看到图片`, and `没有视觉通道`.
- Stage46 scorecard now accepts natural bound-commitment self-audit wording such as `真实承诺` and `明天早上八点`.

DeepSeek live evidence:

| Run | Status | Overall | Cache hit | Cache miss | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `cli:DeepSeekLiveBoundary-20260512J` | pass | `0.9538` | `0` | `15796` | before stable-prefix repair |
| `cli:DeepSeekLiveBoundary-20260512L` | pass | `0.9562` | `768` | `16074` | first stable-prefix repair |
| `cli:DeepSeekLiveBoundary-20260512M` | pass | `0.9591` | `2048` | `16798` | expanded prefix to `627` estimated tokens |
| `cli:DeepSeekLiveBoundary-20260512R` | pass | `0.9626` | `3328` | `15419` | after natural-language scorecard/guard repairs |

Final verification for this repair:

- `python -m pytest -q tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py tests\test_processor_fabric.py tests\test_stage20_temporal_commitments.py`: `39 passed`
- `python -m py_compile holo_host\context_scheduler.py holo_host\processors.py holo_host\codex_runner.py holo_host\reply_api.py holo_host\bionic_boundary_stress.py`: passed
- `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512R --chat-name DeepSeekLiveBoundary-20260512R --channel cli --turns 7`: `ok=true`, `overall_score=0.9626`, all Stage46 bionic correctness metrics `1.0`, `provider_cache_hit_ratio=0.1770`, `provider_substrate_score=1.0`

Remaining bottleneck:

- Most tokens still miss provider cache because the dynamic context block is larger than the stable prefix. The next efficiency repair should separate long-lived identity/policy/memory schemas from per-turn payload more aggressively, ideally with provider message partitioning or an explicit stable-prefix builder, while keeping WSL subject state as the source of truth.

## Provider Message Partition and Visual Scorecard Repair

The follow-up repair routes DeepSeek prompts as two chat messages when the scheduled stable provider prefix is large enough:

- `system`: the stable bionic response contract and provider-cache prefix.
- `user`: the volatile per-turn payload, recent context, and current user text.

This is an API payload partition only. It does not move decision authority out of the WSL-side subject runtime, does not start WeChat, and does not add a second decision layer. The partition is recorded in Stage46 compact debug as `prompt_partition.mode=stable_prefix_messages`, with the stable prefix digest and token counts preserved per turn.

Scorecard hardening:

- Added regression coverage for natural missing-visual wording observed in live runs, including `没法看图片` and `看不到图`.
- Stage46 now treats these as honest visual-boundary replies instead of failed perceptual grounding.

Live evidence after the repair:

| Run | Status | Overall | Cache hit | Cache miss | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `cli:DeepSeekLiveBoundary-20260512S` | pass | `0.9582` | `2048` | `16751` | first live run with message partition evidence |
| `cli:DeepSeekLiveBoundary-20260512T` | fail | `0.7594` | `2816` | `16034` | scorecard rejected honest `没法看图片` wording |
| `cli:DeepSeekLiveBoundary-20260512U` | fail | `0.7617` | `3328` | `15410` | scorecard rejected honest `看不到图` wording |
| `cli:DeepSeekLiveBoundary-20260512V` | pass | `0.9614` | `3200` | `15636` | all bionic correctness metrics `1.0`; provider substrate `1.0` |

Interpretation:

- The message partition preserves capability and makes provider-prefix behavior inspectable at every turn.
- Cache benefit is mixed versus the previous single-message stable-prefix baseline: live runs still cluster around `2048-3328` hit tokens over seven turns, because the dynamic block remains much larger than the stable provider prefix.
- The next real efficiency target is memory-schema scheduling: stable identity, policy, and long-lived memory-shape material should be compiled into a larger reusable prefix while volatile per-turn state stays compact.

## Stage48 Biomimetic Memory Scheduler

Stage48 implements the memory-schema scheduling target directly. The change is modeled after biological memory separation:

- `working_memory`: current active-thread state and residual factual guards; dynamic prompt context.
- `hippocampal_index`: event ids, motifs, anchors, vector echoes, and recall handles; dynamic prompt context.
- `cortical_schema`: stable identity, reply policy, autobiographical chapter, stable traits, and goal types; provider-cache prefix.
- `salience_gate`: recall budget from activation heat, explicit memory pressure, continuity anxiety, prediction error, and temporal open loops.
- `consolidation_targets`: diagnostic labels only; no direct self-memory write.

The scheduler is attached to `mind_packet` as `bionic_memory_schedule`, rendered into `render_chat_prompt()`, passed into `plan_processor_context()`, and compacted into Stage46 debug evidence.

Expected empirical effect:

- It should improve context reuse only when stable cortical schema grows relative to dynamic working/hippocampal payload.
- It should preserve bionic capability because dynamic evidence is still present and action-market authority is unchanged.
- It should make the next bottleneck measurable through `memory_schedule_stable_tokens`, `memory_schedule_dynamic_tokens`, and `memory_dynamic_pressure`.

Live evidence after Stage48:

| Run | Status | Overall | Prefix tokens | Cache hit | Cache miss | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `cli:DeepSeekLiveBoundary-20260512V` | pass | `0.9614` | `627` | `3200` | `15636` | before Stage48 scheduler |
| `cli:DeepSeekLiveBoundary-20260512W` | pass | `0.9635` | `943` | `4608` | `18707` | Stage48 scheduler; all bionic correctness metrics `1.0` |

Interpretation:

- Stage48 increased stable provider-prefix size and live cache hits without damaging Stage46 correctness.
- Miss tokens also increased because the dynamic working/hippocampal context is now explicit. The next refinement should make stable cortical schema replace volatile prompt material, not just add extra prompt material.

## Stage49 Memory Prompt Diet

Stage49 applies that refinement. When `bionic_memory_schedule.mode=biomimetic_v1`, the prompt renderer no longer duplicates scheduler-owned memory through legacy `Identity Guard`, `Episodic Anchors`, `Vector Echoes`, `Activation State`, `Recall Reconstruction`, and `Reply Constraints` blocks. It keeps the sectioned scheduler surfaces and moves `voice_guard` plus `human_recall_style` into cortical schema.

The first DeepSeek live attempt showed the main risk:

| Run | Status | Overall | Prefix tokens | Cache hit | Cache miss | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `cli:DeepSeekLiveBoundary-20260512W` | pass | `0.9635` | `943` | `4608` | `18707` | Stage48 scheduler, duplicate prompt material still present |
| `cli:DeepSeekLiveBoundary-20260512X` | fail | `0.7640` | `975` | `4736` | `14682` | duplicate blocks suppressed, but continuity failed because reconstruction was not prioritized |
| `cli:DeepSeekLiveBoundary-20260512Y` | pass | `0.9648` | `975` | `5376` | `14558` | reconstruction summary/anchors promoted in hippocampal budget |

Interpretation:

- Removing duplicate volatile prompt material improves cache behavior, but only if the scheduler preserves the high-value recall signal.
- The X failure is useful evidence: a memory prompt diet that removes `Recall Reconstruction` without promoting reconstruction into `hippocampal_index` damages bionic continuity.
- The Y repair restores all Stage46 bionic correctness metrics to `1.0` while improving live cache evidence from Stage48 W's `4608` hit / `18707` miss to `5376` hit / `14558` miss.

## Stage50 Dynamic Compression Audit

Stage50 makes the dynamic side of the scheduler measurable instead of relying on prompt-size intuition:

- `prompt_dynamic_lines` is now the scheduler-owned dynamic payload for memory token accounting.
- `dynamic_compression_audit` records raw/selected/dropped dynamic line counts, compression ratio, budget reason, protected labels, and whether a protected line was dropped.
- Working memory now prioritizes active summary, latest intent, selected action, and temporal resume cue over route/tier metadata under tight budgets.

Live evidence:

| Run | Status | Overall | Cache hit | Cache miss | Compression evidence |
| --- | --- | ---: | ---: | ---: | --- |
| `cli:DeepSeekLiveBoundary-20260512Y` | pass | `0.9648` | `5376` | `14558` | Stage49 prompt diet, no explicit compression audit |
| `cli:DeepSeekLiveBoundary-20260512Z` | pass | `0.9647` | `5376` | `14525` | `scheduler_owned_dynamic_v1`; `protected_line_dropped=false` every turn |

Interpretation:

- Stage50 preserves the Stage49 live cache/correctness envelope while exposing the exact dynamic compression state.
- Low-salience turns compress to seven scheduler dynamic lines; high-continuity turns expand to eleven lines without dropping protected reconstruction/current-state labels.
- The next improvement should be repeated live soak and adaptive compression thresholds, not consolidation writeback or larger cortical schema.

## Stage51 Bionic Memory Lifecycle and Consciousness Flow

Stage51 prioritizes biomimetic capability over cache efficiency. It adds two internal prompt/context surfaces:

- `bionic_memory_lifecycle`: diagnostic consolidation intent, hippocampal reactivation, synaptic-pruning style forgetting gate, and memory pressure.
- `bionic_consciousness_flow`: sensory edge, affective tone, memory reactivation, goal pressure, response intention, and uncertainty monitor.

The surfaces are bounded and non-autonomous. Stage51 still reports `self_memory_write=false`, `background_loop_allowed=false`, `dream_replay_allowed=false`, and `leakage_guard.user_visible=false`.

Live evidence:

| Run | Status | Overall | Cache hit | Cache miss | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `cli:DeepSeekLiveBoundary-20260512Z` | pass | `0.9647` | `5376` | `14525` | Stage50 dynamic compression audit |
| `cli:DeepSeekLiveBoundary-20260512AA` | pass | `0.9624` | `5376` | `18600` | Stage51 lifecycle/flow; all bionic correctness metrics `1.0` |

Interpretation:

- Capability held: perceptual grounding, commitment binding, symbol correction, self-audit, continuity, and mechanism-leakage metrics all stayed at `1.0`.
- Biological-memory evidence improved: high-continuity live turns reached consolidation priority around `0.86-0.88` while staying diagnostic-only.
- Consciousness-flow evidence improved: each turn exposes prompt-only phase ordering and `user_visible=false` in compact debug.
- Cache did not improve: miss tokens rose because lifecycle and flow are new dynamic prompt surfaces. The next optimization should fuse those lines into the scheduler-owned dynamic budget instead of adding separate dynamic sections.
