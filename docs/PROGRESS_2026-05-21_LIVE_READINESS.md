# Progress - Live Readiness Gate - 2026-05-21

## Context

After moving live speech generation to the DeepSeek provider, `/health` could
still report `ok` while hiding important long-running risks:

- the speech dispatch chain might still include `codex_cli`
- DeepSeek might be configured but unavailable through the expected secret
- vector memory might be present but not ready
- recent processor failures might accumulate without a single operator-facing
  summary

For Holo as a long-running single-subject runtime, process liveness is not
enough. Operators need a compact answer to whether the subject can keep speaking
through the intended provider path.

## Decision

Add a live readiness surface that combines:

- `/health`
- provider availability
- reply task dispatch
- vector backend readiness
- brain mode
- latest processor usage state, with recent errors still included as evidence

The readiness gate marks the system `ready` only when live speech is visible,
the primary speech provider is available, required lane primaries are available,
the speech path is not Codex-dependent, and the latest processor usage record is
not an error. Recent processor errors remain visible in the payload so old
failures are not hidden, but they do not permanently block readiness after a
newer successful provider call.

## Implementation Notes

- Service method: `HoloReplyService.live_readiness()`.
- HTTP endpoint: `GET /live-readiness`.
- CLI command: `python3 -m holo_host show-live-readiness`.
- `scripts/holo-status.sh` prints readiness status and failed checks after the
  health payload.
- The readiness probe is dispatch-only for providers. It does not spend provider
  tokens.
- If the vector backend is available but not initialized in the live process,
  readiness performs a lightweight vector-client warmup before deciding
  `vector_ready`.
- `accept_processor_fabric` now requires the DeepSeek provider contract to be
  visible alongside existing provider adapters.

## Follow-up Fix

Live readiness exposed reply errors where the legacy `CodexRunner.run()` path
sent the Codex model override to the DeepSeek backend. That made live reply
tasks attempt `gpt-5.4` against DeepSeek instead of using the lane model
`deepseek-v4-pro`.

The fix is to only auto-fill `codex_model` and `codex_reasoning_effort` for the
`codex_cli` backend. DeepSeek and other processor-fabric providers now let the
lane configuration choose the provider model and reasoning level.

The Windows CLI also now tries the standard WSL live API port `8004` before
falling back to local-process inspection. This keeps operator checks pointed at
the WSL brain when the Windows checkout only has a transport-side/default
configuration.

## Verification Targets

- `python -m pytest tests/test_holo_host.py::HoloLiveReadinessTests -q`
- `python -m pytest tests/test_holo_host.py::CodexRunnerTests tests/test_processor_fabric.py -q`
- `python -m holo_host show-live-readiness`
- WSL live restart followed by `GET /live-readiness`

## Verified

- `python -m pytest -q`: 264 passed.
- Windows `python -m holo_host show-live-readiness`: `ready`, resolved through
  the WSL live API on port `8004`.
- WSL `python3 -m holo_host show-live-readiness`: `ready`.
- `scripts/holo-status.sh`: prints `readiness: ready
  http://0.0.0.0:8004/live-readiness`.
- Live `/reply` smoke recorded usage id `71`: task `reply`, lane
  `subject_main`, provider `deepseek`, model `deepseek-v4-pro`, status `ok`.
