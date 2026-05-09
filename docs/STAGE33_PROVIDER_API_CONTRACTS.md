# Stage33 Provider API Contracts

## What Stage33 Closes
- Makes processor provider API surfaces explicit and inspectable.
- Corrects `openai_compatible` to use chat-completions instead of the OpenAI Responses API.
- Adds `show-provider-contracts`.
- Adds `accept-stage33`.

## Runtime Scope
- Stage33 is provider-fabric work only.
- It does not start WeChat or any live transport.
- It does not add raw model calls outside `CodexRunner` provider classes.
- It does not mutate self-memory, policy, Mind Graph, or subject-loop state.

## Provider Contract Matrix
- `codex_cli`: `codex.exec`
- `responses`: `responses.create`
- `openai_compatible`: `chat.completions`
- `deepseek`: `chat.completions`

## Compatibility Rule
OpenAI-compatible providers are assumed to support the common chat-completions protocol. The Responses API remains reserved for the first-party `responses` provider.

## Validation
- `pytest -q tests/test_stage33_provider_contracts.py tests/test_processor_fabric.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage33`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
