# Stage33 Engineering Handoff

## Status
Stage33 hardens provider/API compatibility by making provider contracts explicit and correcting the generic OpenAI-compatible path to use chat-completions.

## Code Surfaces
- `holo_host/codex_runner.py`
  - adds provider contract metadata and `provider_contracts()`
  - keeps `responses` on `responses.create`
  - moves `openai_compatible` to `chat.completions`
- `holo_host/reply_api.py`
  - adds `provider_contracts()` and `accept_stage33()`
  - exposes HTTP mirrors `/provider-contracts` and `/accept-stage33`
- `holo_host/cli.py`
  - adds `show-provider-contracts` and `accept-stage33`

## Acceptance Contract
`accept-stage33` checks:
- provider contracts are visible
- `openai_compatible` uses `chat.completions`
- `deepseek` uses `chat.completions`
- `responses` remains on `responses.create`
- API providers do not claim image support
- processor-fabric boundaries remain preserved

## Boundaries
- No live transport start.
- No direct provider calls outside provider classes.
- No self-memory, policy, Mind Graph, or subject-loop mutation.
- No new scheduler, loop, or hidden planner.

## Validation Commands
- `pytest -q tests/test_stage33_provider_contracts.py tests/test_processor_fabric.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage33`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
