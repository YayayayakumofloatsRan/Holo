# Engineering Handoff: Stage37

Stage37 is implemented as an internal bionic self-evaluation and capability-honesty repair pass.

## What Changed
- Added same-thread bionic trace continuity for CLI bionic turns.
- Added provider-backed generation guards for empty continuity, text-provider image overclaiming, excessive question marks, and markdown emphasis.
- Added speech fallback when a CLI self-evaluation probe would otherwise select a non-executable internal action.
- Added `accept-stage37`.
- Added `tests/test_stage37_bionic_self_eval.py`.

## Current Debt Position
- Autonomous inquiry formatting remains resolved by Stage36.
- Bionic self-eval/capability honesty is now resolved by Stage37.
- Real image understanding is still not solved for text-only providers; Stage37 only prevents overclaiming and points to `ingest-image` / visual-memory or a real `image_understand` provider. Stage38 closes the internal CLI bridge for explicit image input through `image_understand`.
- Live WeChat hardening, latency/cache soak, replay fixture breadth, and `reply_api.py` facade size remain explicit debts.

## Non-Negotiables
- No WeChat watcher start.
- No self-memory mutation from bionic self-evaluation.
- No action-market bypass; fallback must choose a candidate already present in the market.
- No raw provider call outside the processor fabric.
- No second brain, hidden planner, or new unbounded loop.

## Validation
Verified on `2026-05-09`: all commands below passed, with full `pytest -q` at `298` tests. `git diff --check` reported no whitespace errors.

```powershell
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
pytest -q tests/test_stage37_bionic_self_eval.py tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py tests/test_stage35_internal_runtime_readiness.py
python -m holo_host --config .holo_host.toml accept-stage37 --thread-key cli:TestUser --chat-name TestUser --channel cli
pytest -q
python scripts/check_public_release_hygiene.py
git diff --check
```

## Next Work
Stage38 has now closed the internal CLI image bridge. The next substantive debts are provider latency/cache soak, replay-backed `reply_api.py` facade slimming, replay fixture expansion from a concrete regression, or operator-approved live WeChat hardening.
