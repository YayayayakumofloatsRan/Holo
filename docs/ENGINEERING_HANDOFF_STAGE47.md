# Engineering Handoff Stage47

## Status

Stage47 adds a provider-substrate conflict monitor. Its purpose is to prevent high-intensity biomimetic tests from treating provider/key/model/fallback failures as subject-capability failures.

This remains a diagnostic layer inside the processor fabric:

- WSL remains the authoritative kernel.
- Windows remains transport and history/artifact helper only.
- The watcher does not gain decision authority.
- No WeChat transport is started.
- No self-memory is mutated.

## Modified Surfaces

- `holo_host/provider_substrate.py`
  - Adds `analyze_provider_substrate_conflicts()`.
  - Detects unavailable active providers, unavailable configured primary providers, fallback provider use, and provider/model mismatches.
- `holo_host/codex_runner.py`
  - Adds `provider_substrate_status()`.
- `holo_host/reply_api.py`
  - Adds `provider_substrate_status()` and HTTP `GET /provider-substrate-status`.
- `holo_host/cli.py`
  - Adds `show-provider-substrate-status`.
- `holo_host/bionic_boundary_stress.py`
  - Preserves `fallback_provider` and `provider_failures` in compact processor debug.
  - Adds `provider_substrate_score` and `provider_substrate_conflict` to Stage46 scorecards.
  - A real run with substrate conflicts is downgraded instead of being counted as clean biomimetic evidence.
- `tests/test_processor_fabric.py`
  - Covers unavailable active DeepSeek plus fallback attribution.
- `tests/test_stage46_bionic_boundary_stress.py`
  - Covers Stage46 scorecard downgrading when provider substrate conflicts are present.

## Diagnostic Meaning

The monitor treats these as substrate conflicts:

- `active_provider_unavailable`: active backend alias points at an unavailable provider, such as missing `DEEPSEEK_API_KEY`.
- `configured_primary_unavailable`: a configured lane primary provider is unavailable.
- `fallback_provider_in_effect`: a task reached another provider after one or more provider failures.
- `provider_model_mismatch`: an actual provider received a model family that does not match the provider, such as `codex_cli` receiving a `deepseek-*` model.

Stage46 uses this as an anterior-cingulate-style conflict signal: if declared provider, actual provider, model, or fallback evidence disagree, the scorecard is not clean biomimetic evidence.

## Verified On 2026-05-12

- `python -m pytest -q tests\test_processor_fabric.py tests\test_stage33_provider_contracts.py tests\test_stage46_bionic_boundary_stress.py`: `18 passed`
- `python -m pytest -q`: `369 passed`
- `python -m holo_host show-provider-substrate-status`: returned `ok=false` in the current process because `DEEPSEEK_API_KEY is not set`
- `python -m holo_host run-bionic-boundary-stress --offline --thread-key cli:Stage47Verify-20260512 --chat-name Stage47Verify-20260512`: `ok=True`, `overall_score=0.9896`, `provider_substrate_score=1.0`
- `python -m py_compile holo_host\provider_substrate.py holo_host\bionic_boundary_stress.py holo_host\codex_runner.py holo_host\reply_api.py holo_host\cli.py`: passed
- `python scripts\check_public_release_hygiene.py`: passed
- `git diff --check`: no whitespace errors; Git reported only CRLF conversion warnings for existing text files

## Follow-Up

- Restart the live API before trusting `/provider-substrate-status` from the server process.
- Inject a real DeepSeek key, rerun Stage46, and compare `provider_substrate.ok=true` runs against prior offline scorecards.
- Extend the monitor with stable-prefix cache evidence: when provider cache miss tokens stay high despite stable prompt digests, mark it as context-scheduling evidence rather than response-quality evidence.
