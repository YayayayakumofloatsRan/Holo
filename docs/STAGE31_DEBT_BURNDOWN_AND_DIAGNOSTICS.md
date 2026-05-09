# Stage31 Debt Burn-Down And Diagnostics

## What Stage31 Closes
- Adds an explicit adapter registry so CLI, synthetic WeChat, HTTP, and future adapters share a visible interface-only contract.
- Adds a controlled state-update gate for the offline subject-loop path.
- Adds operational subject-loop trace and metrics diagnostics.
- Extracts bionic CLI payload helpers into `holo_host/cli_parts/bionic.py`.
- Adds `accept-stage31`.

## Debt Burned Down
- `adapter registry`: `holo_host/adapter_registry.py` now centralizes adapter contracts.
- `state update gate`: `holo_host/subject_loop/state_update_gate.py` rejects self-memory, policy, Mind Graph, transport, scheduler, and second-brain writes from the offline subject loop.
- `subject-loop diagnostics`: `QueueStore.trace_subject_loop(...)` and `QueueStore.latest_subject_loop_metrics(...)` expose operational traces and invariant pass rates.
- `CLI bionic helper sprawl`: bionic payload assembly moved out of the top-level CLI module.

## Remaining Non-Code Blockers
- Live WeChat validation remains intentionally blocked until restart is explicitly approved.
- Real visual-provider hardening still requires a configured image-capable provider.
- `reply_api.py` remains a large runtime facade and should be split only with a dedicated compatibility plan.

## Validation
- `pytest -q tests/test_stage31_debt_burndown.py tests/test_stage30_subject_loop.py tests/test_stage29_bionic_cli_agent.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage31 --thread-key TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
