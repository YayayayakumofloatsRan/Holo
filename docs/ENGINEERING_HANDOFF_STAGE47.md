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
  - Resolves DeepSeek API keys from process env first and Windows user/machine environment registry second.
  - Exposes `api_key_source` as `process`, `windows_registry`, or empty without printing the secret.
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

## DeepSeek User-Environment Repair - 2026-05-12

The apparent missing-key failure was a process-inheritance problem, not absence of a local key. `DEEPSEEK_API_KEY` existed in Windows User environment, but the current Codex/PowerShell/Python process did not inherit it through `os.environ`.

Repair:

- `DeepSeekProvider` now resolves the configured key env var through `os.environ` first, then the Windows environment registry.
- Provider status reports `api_key_source=windows_registry` when the fallback path is used.
- No status output prints the key value.

Fresh verification after the repair:

- `python -m pytest -q tests\test_processor_fabric.py -k "deepseek_provider_status or deepseek_provider_returns_standardized_result or deepseek_provider_reuses_cached_response"`: `4 passed, 9 deselected`
- `python -m pytest -q tests\test_processor_fabric.py tests\test_stage33_provider_contracts.py tests\test_stage46_bionic_boundary_stress.py`: `19 passed`
- `python -m py_compile holo_host\codex_runner.py`: passed
- `python -m holo_host show-provider-substrate-status`: `ok=true`, `score=1.0`, `deepseek.available=true`, `api_key_source=windows_registry`
- `python -m holo_host processor-task --task-type reply --prompt "请用一句话回应：收到" --lane micro_fast --provider-hint deepseek --max-output-tokens 20`: returned through `provider=deepseek`, `model=deepseek-v4-flash`, `duration_ms=1642`, real token usage, and no fallback

Note: `processor-task --json` can still create a separate `response_format=json_object` failure for non-JSON prompts and then fall back. That is not an API-key failure.

## Follow-Up

- Restart any live API process that predates this patch before trusting `/provider-status` or `/provider-substrate-status` from the server process.
- Rerun Stage46 against live DeepSeek with `provider_substrate.ok=true` and compare against prior offline scorecards.
- Extend the monitor with stable-prefix cache evidence: when provider cache miss tokens stay high despite stable prompt digests, mark it as context-scheduling evidence rather than response-quality evidence.

## DeepSeek Live Bionic Stress Calibration - 2026-05-12

See `docs/DEEPSEEK_MODEL_BIONIC_STRESS_2026-05-12.md` for the full run notes.

Key outcome:

- `GET https://api.deepseek.com/models` returned `deepseek-v4-flash` and `deepseek-v4-pro`.
- Compatibility aliases `deepseek-chat` and `deepseek-reasoner` still work but returned through `deepseek-v4-flash`.
- Thinking-mode probes can spend all capped output tokens on `reasoning_content`, leaving final `content` empty; normal replies should stay non-thinking.
- `CodexResult` now preserves processor metadata so Stage46 transcripts can prove actual provider/model/usage instead of only configured substrate.
- Strict live Stage46 run `cli:DeepSeekLiveBoundary-20260512D` failed with `overall_score=0.8142` because self-audit contradicted the already-bound reminder state.
- Residual fast channel repair added WSL-side introspective commitment/visual facts to reply prompts and post-generation guards.
- Live Stage46 run `cli:DeepSeekLiveBoundary-20260512J` passed with `overall_score=0.9538`, `provider_substrate_score=1.0`, `commitment_binding_score=1.0`, `perceptual_grounding_score=1.0`, and `self_audit_score=1.0`.

Next repair: provider-aware stable-prefix reuse and memory scheduling. The J run still recorded `0` prompt-cache hit tokens and `15796` miss tokens, so the next efficiency target is prompt/context layout rather than biomimetic correctness.
