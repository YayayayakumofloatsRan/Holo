# Engineering Handoff: Stage38

Stage38 is implemented as the internal visual-provider bridge for bionic CLI image input.

## What Changed
- Added `BionicTurnRequest.image_paths`.
- Added `agent-run --image-path`.
- Added `MemoryBridge.ingest_image()` provider metadata preservation under `image_understand`.
- Added `perception.stage38` to bionic capsules.
- Added visual-grounding prompt context for provider-backed bionic generation.
- Added CLI visual-recall speech fallback when `visual_recall` wins the market.
- Added `accept-stage38`.
- Added `tests/test_stage38_visual_provider_bridge.py`.

## Current Debt Position
- Visual-provider readiness is now resolved for the internal CLI path: explicit image input can be routed through image-capable `image_understand`, persisted as visual memory, and used by bionic generation without overclaiming text-provider vision.
- DeepSeek remains text-only for image support. If a future DeepSeek-compatible vision endpoint appears, it must be added as a provider contract change inside the processor fabric.
- Live WeChat hardening, latency/cache soak, replay fixture breadth, and `reply_api.py` facade size remain explicit debts.

## Non-Negotiables
- No WeChat watcher start.
- No transport decision authority in CLI or visual input.
- No raw provider calls outside the processor fabric.
- No direct image-reading claim from a text-only generation provider.
- No second brain, hidden planner, or new unbounded loop.

## Validation
```powershell
$env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
pytest -q tests/test_stage38_visual_provider_bridge.py tests/test_stage37_bionic_self_eval.py tests/test_stage34_debt_closure.py tests/test_stage28_multimodal_homeostatic_kernel.py tests/test_stage29_bionic_cli_agent.py
python -m holo_host --config .holo_host.toml accept-stage38 --thread-key cli:TestUser --chat-name TestUser --channel cli
pytest -q
python scripts/check_public_release_hygiene.py
git diff --check
```

Verified on `2026-05-10`: the targeted Stage38 suite passed, `accept-stage38` passed, full `pytest -q` passed with `301` tests, public-release hygiene passed, and `git diff --check` reported no whitespace errors.

## Operator Probe
```powershell
python -m holo_host --config .holo_host.toml agent-run --query "What is visible in this screenshot?" --thread-key cli:VisualProbe --chat-name VisualProbe --channel cli --image-path D:\path\to\image.png
```

## Next Work
The next substantive debts are provider latency/cache soak, replay-backed `reply_api.py` facade slimming, replay fixture expansion from concrete regressions, or operator-approved live WeChat hardening.
