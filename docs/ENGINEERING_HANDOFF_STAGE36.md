# Engineering Handoff: Stage36

Stage36 is implemented as an offline bionic-kernel inquiry-quality gate.

## What Changed
- Added grounded inquiry-quality scoring to deterministic fallback generation.
- Removed `Next:` / `Basis:` / `Open:` / `Context:` label-template output from the bionic deterministic fallback.
- Added `formatting_pressure_score`, `inquiry_quality_score`, and `question_count` to bionic metrics.
- Added `accept-stage36` in the CLI path.
- Added `tests/test_stage36_inquiry_quality.py`.
- Updated the debt registry so `autonomous-inquiry-quality` is resolved by Stage36 rather than left as planned debt.

## Current Debt Position
- Autonomous inquiry formatting debt is now acceptance-gated by Stage36.
- Internal DeepSeek runtime readiness remains machine-checkable by Stage35.
- Visual-provider readiness remains bounded by Stage34; real image-capable provider hardening still requires configured-provider soak.
- WeChat watcher hardening, live reply availability, and multi-hour latency/cache/fallback quality remain external-precondition debts.
- `reply_api.py` facade size remains bounded structural debt and must not be split without replay-backed compatibility tests.
- Replay fixture breadth remains intentionally narrow and should grow only from concrete regression evidence.

## Non-Negotiables
- No live WeChat transport start.
- No self-memory mutation.
- No action-market bypass.
- No raw provider calls outside the processor fabric.
- No second brain, hidden planner, or new unbounded loop.
- No unredacted secret in diagnostics or docs.

## Validation
```powershell
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
pytest -q tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py tests/test_stage35_internal_runtime_readiness.py
python -m holo_host --config .holo_host.toml accept-stage36 --thread-key cli:TestUser --chat-name TestUser --channel cli
pytest -q
python scripts/check_public_release_hygiene.py
git diff --check
```

## Next Work
Stage37 has now closed the immediate bionic self-eval and capability-honesty failures found by direct internal dialogue probes. The next code-bearing work should target one explicit remaining debt at a time: real visual-provider integration, provider latency/cache soak, replay-backed `reply_api.py` facade slimming, replay fixture expansion from a real regression, or operator-approved live WeChat hardening.
