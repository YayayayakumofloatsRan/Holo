# Engineering Handoff Stage45

## Status

Stage45 repairs two high-intensity biomimetic failures and adds the first processor-context scheduler for model-context efficiency.

This is still inside the host-side processor fabric:

- WSL remains the authoritative kernel.
- Windows remains transport and history/artifact helper only.
- The watcher does not gain decision authority.
- DeepSeek remains accessed through the processor fabric, not raw hot-path calls.
- Live WeChat transport was not started during this pass.

## Modified Surfaces

- `holo_host/reply_api.py`
  - Adds post-generation perceptual grounding for current-image questions.
  - Rewrites visual overclaims when no current visual grounding exists.
  - Binds explicit reminder promises to temporal memory state.
  - Rewrites unbound reminder promises instead of pretending a scheduler exists.
- `holo_host/context_scheduler.py`
  - Adds context-window classification for `8k`, `128k`, and `1m` lanes/models.
  - Adds CJK-aware token pressure estimation.
  - Splits stable and volatile prompt digests.
  - Trims history and opens a new processor session under high context pressure.
- `holo_host/processors.py`
  - Calls the context scheduler before DeepSeek/Codex runner invocation.
  - Re-renders prompts after scheduler history trimming.
  - Propagates `context_schedule` into runner metadata and reply debug output.
- `holo_host/codex_runner.py`
  - Records `cache_mode=exact_response` and context-schedule metadata in usage rows.
  - Preserves DeepSeek `usage.prompt_cache_hit_tokens` and `usage.prompt_cache_miss_tokens` for real provider-cache analysis.
- `holo_host/store.py`
  - Reports response-cache stats as exact-response cache diagnostics.
- `tests/test_holo_host.py`
  - Covers unseen-image overclaim rewriting, reminder binding, and no false commitment for plain future talk.
- `tests/test_context_scheduler.py`
  - Covers high-pressure Flash session renewal, stable/volatile digest splitting, and CJK token pressure.

## Cache Diagnosis

DeepSeek official context-cache docs (`https://api-docs.deepseek.com/guides/kv_cache`) say the API reports `usage.prompt_cache_hit_tokens` and `usage.prompt_cache_miss_tokens`, and that cache matching is prefix-based, best-effort, and built after prior matching requests.

The observed local response-cache profile is:

- `entries=55`
- `hits=0`
- `misses=55`
- `hit_ratio=0.0`

This is expected for the current cache mode. `processor_response_cache` keys the complete rendered prompt, so ordinary dialogue misses when the current turn, recent history, or runtime state changes.

The Stage45 change does not overclaim provider-level prefix caching. It makes the cache mode explicit and adds `context_schedule` metadata so future work can separate stable system/identity context from volatile turn/history context, then decide when to reuse a processor session and when to open a fresh one.

## Verified On 2026-05-12

- `python -m pytest -q tests\test_context_scheduler.py`: `3 passed`
- `python -m pytest -q tests\test_holo_host.py -k "unseen_image_overclaim or reminder_language or plain_future_talk or recall_reconstruct or windows_history_refresh or high_risk_continuity"`: `5 passed, 61 deselected`
- `python -m pytest -q tests\test_processor_fabric.py -k "response_cache or deepseek_provider"`: `5 passed, 4 deselected`
- `python -m pytest -q tests\test_processor_fabric.py`: `9 passed`
- `python -m pytest -q tests\test_holo_host.py`: `66 passed`
- `python -m pytest -q tests\test_cache_diagnostics.py`: `3 passed`
- `python -m pytest -q tests\test_stage40_deepseek_v4_profile.py`: `3 passed`
- `python -m pytest -q tests\test_stage40_context_compiler.py`: `2 passed`
- `git diff --check`: no whitespace errors
- Local provider-status construction reports `response_cache.cache_mode=exact_response` with diagnostic note.

## Follow-Up

- Add provider-aware stable-prefix reuse if the active DeepSeek API surface exposes a usable context-cache mechanism.
- Add a compact biomimetic regression suite from the valid high-intensity stress probes.
- Extend grounding guards to positive image-provider evidence and broader follow-up/initiative commitments.
- Restart the live API process before treating `/provider-status` as evidence for the new cache diagnostic fields.
