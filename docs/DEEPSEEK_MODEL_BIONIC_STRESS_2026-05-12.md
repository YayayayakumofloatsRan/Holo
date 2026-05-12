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
