# Stage31 Engineering Handoff

## Status
Stage31 burns down the immediate Stage29/30 architecture debt that can be completed offline without live transport or private memory.

## Code Surfaces
- `holo_host/adapter_registry.py`
  - defines interface-only adapter contracts
- `holo_host/subject_loop/state_update_gate.py`
  - centralizes offline subject-loop write decisions
- `holo_host/cli_parts/bionic.py`
  - owns bionic CLI payload helpers and Stage29/30/31 acceptance payloads
- `holo_host/store.py`
  - adds `trace_subject_loop(...)` and `latest_subject_loop_metrics(...)`
- `holo_host/cli.py`
  - keeps command wrappers and parser wiring only for the bionic commands

## Acceptance Contract
`accept-stage31` checks:
- Stage30 acceptance still passes
- adapter registry is visible and interface-only
- state-update gate is visible in the subject loop
- subject-loop trace and metrics diagnostics are visible
- bionic CLI payload helpers are extracted from the top-level CLI module

## Boundaries
- No WeChat start.
- No live transport send path.
- No self-memory, policy, or Mind Graph write from the offline subject-loop path.
- No raw provider call outside processor fabric.

## Validation Commands
- `pytest -q tests/test_stage31_debt_burndown.py tests/test_stage30_subject_loop.py tests/test_stage29_bionic_cli_agent.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage31 --thread-key TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
