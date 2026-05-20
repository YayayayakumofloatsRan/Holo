# Progress - DeepSeek Provider Default - 2026-05-20

## Context

Holo app transport from Android to Windows/WSL reached the reply API, but live `/reply` calls timed out while the processor tried to use `codex_cli`.

Observed runtime evidence:

- WSL API health was available on port `8004`.
- Android-to-host routing used `adb reverse tcp:8004 tcp:8004`.
- `/reply` entered Holo but the provider layer logged repeated Codex authentication/network failures, including `unsupported_country_region_territory`.

Conclusion: the phone/WSL transport was not the primary blocker. The production speech provider was.

## Decision

Default live text generation now uses DeepSeek as the primary provider:

- `deepseek-v4-pro` for `subject_main` and `kernel_xhigh`.
- `deepseek-v4-flash` for `micro_fast`.
- OpenAI-compatible HTTP remains the configurable external fallback.
- Codex CLI is now an explicit development/operator fallback, not a silent live-reply dependency.

## Implementation Notes

- Provider calls stay inside the provider abstraction.
- DeepSeek uses HTTP `chat/completions`.
- `DEEPSEEK_API_KEY` is the default secret source.
- `DEEPSEEK_BASE_URL` can override the default endpoint.
- `OPENAI_COMPATIBLE_API_KEY` and `OPENAI_COMPATIBLE_BASE_URL` remain available for non-DeepSeek compatible backends.
- Holo app live replies set a bounded processor timeout so the UI is not held by a failing backend for minutes.

## Verification Targets

- `python -m pytest tests/test_processor_fabric.py tests/test_stage17_realtime_runtime.py tests/test_stage18_dual_speed_reflex.py -q`
- `python -m pytest tests/test_holo_host.py -q`
- WSL live smoke after restart: `/health`, `/processor-routing`, and a short `/reply` request.
