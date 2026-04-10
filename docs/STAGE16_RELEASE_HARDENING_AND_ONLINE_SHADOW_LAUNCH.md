# Stage16 Release Hardening And Online Shadow Launch

## Goal

Stage16 seals release blockers before online shadow testing. It does not add a new subject surface; it hardens the harness around the existing subject runtime.

## Boundary

- No second brain layer.
- No new always-on daemon loop.
- No operator safety weakening and no live repo hot edits.
- Preserve memory-is-self, processor-replaceable, transport-eyes-hands, and action-market-first deliberation.

## What Changed

- Helper artifact path conversion is direction-aware:
  - Holo-host-facing paths normalize to `/mnt/<drive>/...`.
  - Windows-helper-facing paths normalize to `X:\...`.
- WSL fallback now follows endpoint topology: localhost and `127.0.0.1` may try WSL fallback; explicit remote hosts do not.
- Stage14 replay metrics keep raw aggregate values and deterministic display rounding.
- Stage12 acceptance uses deterministic acceptance-only appraisal evidence when running locally, so processor availability does not decide the gate.
- Stage12 action-market-first checks accept valid non-speech selected actions such as `silence` and `defer_reply`.
- Policy defaults and autobiographical outcome text were cleaned back to UTF-8 readable self-narrative strings.

## Acceptance Checklist

- `pytest -q` passes.
- `python -m holo_host --config .holo_host.example.toml accept-stage12` passes.
- `python -m holo_host --config .holo_host.example.toml accept-stage14` passes.
- `python -m holo_host --config .holo_host.example.toml accept-stage16` passes.

`accept-stage16` checks full local test readiness, Stage12 deterministic acceptance, Stage14 replay acceptance, UTF-8 text integrity, helper path roundtrip, localhost-to-WSL fallback, replay artifact generation, shadow-launch config sanity, and action-market-first alignment.

## Shadow Launch

Keep Holo stopped until Stage16 is green. For a shadow run, start only the WSL host and Windows helper transport in draft-safe mode, verify `/health`, helper path conversion, and fallback candidates, then observe ledger/appraisal/action-market traces without enabling new autonomous behavior.
