# Engineering Handoff: Stage35

Stage35 is implemented as an internal runtime readiness gate.

## What Changed
- Added `holo_host/runtime_readiness.py` for secret scanning, DeepSeek lane checks, env-key presence checks, and WeChat transport quiescence.
- Added CLI/HTTP diagnostics:
  - `show-internal-runtime-readiness`
  - `/internal-runtime-readiness`
- Added `accept-stage35` and `/accept-stage35`.
- Added `tests/test_stage35_internal_runtime_readiness.py`.
- Updated the debt registry so internal startup readiness is resolved by Stage35, while live WeChat hardening and latency/cache soak remain explicit external-precondition debts.

## Current Debt Position
- Internal DeepSeek runtime readiness is now machine-checkable.
- Provider contract drift remains resolved by Stage33.
- Fixed fallback template pressure remains resolved by Stage32.
- Visual-provider readiness remains bounded by Stage34; real image-capable provider hardening still requires configured-provider soak.
- WeChat watcher hardening, live reply availability, and multi-hour latency/cache/fallback quality remain external-precondition debts.
- `reply_api.py` facade size remains bounded structural debt and must not be split without replay-backed compatibility tests.

## Non-Negotiables
- No live WeChat transport start.
- No model call during Stage35 acceptance.
- No self-memory mutation.
- No raw provider calls outside the processor fabric.
- No unredacted secret in diagnostics.
- No new unbounded loop or second brain.

## Validation
```powershell
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
pytest -q tests/test_stage35_internal_runtime_readiness.py
python -m holo_host --config .holo_host.toml show-internal-runtime-readiness
python -m holo_host --config .holo_host.toml accept-stage35
pytest -q
python scripts/check_public_release_hygiene.py
git diff --check
```

## Next Work
The next code-bearing work should target one explicit remaining debt at a time: autonomous inquiry quality, real image-provider integration, provider latency/cache soak, or a replay-backed `reply_api.py` facade split. Do not restart WeChat or widen live transport without a separate operator-approved live-soak plan.
