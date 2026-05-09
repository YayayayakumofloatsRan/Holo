# Stage32 Engineering Handoff

## Status
Stage32 reduces the immediate template-pressure debt in the offline bionic subject kernel. It keeps the same subject-loop and adapter boundaries while making deterministic fallback replies more context-shaped.

## Code Surfaces
- `holo_host/bionic_kernel_parts/response_shaping.py`
  - builds bounded fallback text from query, continuity, selected action reason, modalities, and open questions
- `holo_host/bionic_kernel_parts/generation.py`
  - delegates offline fallback text to the response-shaping helper
- `holo_host/bionic_kernel_parts/metrics.py`
  - exposes `context_shaping_score`
- `holo_host/cli_parts/bionic.py`
  - adds `accept_stage32_payload(...)`
- `holo_host/cli.py`
  - adds `accept-stage32`

## Acceptance Contract
`accept-stage32` checks:
- Stage31 acceptance still passes
- deterministic fallback generation remains visible
- fixed fallback template markers are absent
- context-shaping metadata is visible
- `context_shaping_score` is positive
- `template_pressure_score` is zero for the probe turn

## Boundaries
- No live transport start.
- No self-memory, policy, or Mind Graph mutation.
- No new provider path outside processor fabric.
- No new loop, scheduler, or second-brain layer.

## Validation Commands
- `pytest -q tests/test_stage32_response_shaping.py tests/test_stage31_debt_burndown.py tests/test_stage29_bionic_cli_agent.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage32 --thread-key TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
