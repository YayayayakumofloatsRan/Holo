# Engineering Handoff: Stage34

Stage34 is implemented as an offline debt-closure gate.

## What Changed
- Added `holo_host/debt_registry.py` as the source of truth for current technical debt classification.
- Added visual-provider readiness diagnostics on `CodexRunner` without live model calls.
- Added CLI/HTTP diagnostics:
  - `show-debt-registry`
  - `show-visual-provider-readiness`
  - `/debt-registry`
  - `/visual-provider-readiness`
- Added `accept-stage34` and `/accept-stage34`.
- Added `tests/test_stage34_debt_closure.py`.

## Current Debt Position
- Provider contract drift is resolved by Stage33.
- Fixed fallback template pressure is resolved by Stage32.
- Visual-provider readiness is now bounded by Stage34 diagnostics; real provider hardening still requires configured image-capable lanes and explicit live soak.
- WeChat watcher fragility, latency/cache/fallback soak, and live reply availability remain external-precondition debts while Holo is intentionally offline.
- `reply_api.py` facade size remains bounded structural debt. Do not split it opportunistically; split only behind dedicated compatibility tests and acceptance gates.

## Non-Negotiables
- No live transport start.
- No self-memory mutation.
- No raw provider calls outside the processor fabric.
- No new unbounded loop.
- No transport-side decision logic.
- Action-market-first remains preserved.

## Validation
```powershell
pytest -q tests/test_stage34_debt_closure.py tests/test_stage33_provider_contracts.py tests/test_stage32_response_shaping.py
python -m holo_host --config .holo_host.example.toml accept-stage34
pytest -q
python scripts/check_public_release_hygiene.py
git diff --check
```

## Next Work
The next substantial work should be explicit Stage35 planning, likely focused on autonomous inquiry quality and real visual-provider soak. It should not start Holo until the operator explicitly approves restart testing.
