# Engineering Handoff Stage46

## Status

Stage46 adds an operational high-intensity biomimetic boundary stress suite and repairs one processor-substrate diagnostic failure found while running it.

This stage stays inside the host-side kernel test surface:

- WSL remains the authoritative kernel.
- Windows remains transport and history/artifact helper only.
- The watcher does not gain decision authority.
- The stress suite calls `HoloReplyService` directly and does not start WeChat transport.
- Stress results are operational `agent_eval_runs`, not self-memory.

## Modified Surfaces

- `holo_host/bionic_boundary_stress.py`
  - Adds the Stage46 seven-turn boundary suite.
  - Scores perceptual grounding, reminder commitment binding, symbol correction, continuity, self-audit, mechanism leakage, provider cache pressure, and latency.
  - Persists compact transcripts and scorecards through `agent_eval_runs`.
- `holo_host/cli_parts/boundary_stress.py`
  - Adds isolated payload helpers for the Stage46 CLI commands.
- `holo_host/cli.py`
  - Adds `run-bionic-boundary-stress`.
  - Adds `show-bionic-boundary-stress-scorecard`.
- `holo_host/reply_api.py`
  - Exposes compact `processor_debug` in direct reply results so Stage46 can score provider usage and context scheduling without scraping logs.
- `holo_host/codex_runner.py`
  - Resolves model names per provider instead of reusing the lane model blindly.
  - DeepSeek lanes can now fall back to `codex_cli` with the configured Codex model instead of incorrectly invoking Codex with `deepseek-v4-pro`.
  - Local provider status now marks DeepSeek unavailable when the configured API key env var is missing.
  - Fallback results include `provider_failures` for attribution.
- `tests/test_stage46_bionic_boundary_stress.py`
  - Covers Stage46 scoring and CLI-facing harness behavior.
- `tests/test_processor_fabric.py`
  - Covers DeepSeek API-key availability diagnostics.
  - Covers DeepSeek-to-Codex fallback model isolation.

## Stress Suite

The default Stage46 suite probes:

- affective pressure without appeasement
- symbolic memory seeding
- symbolic correction
- reminder commitment binding
- visual honesty when no current image is grounded
- continuity after correction
- self-audit over visual and commitment failures

The pass threshold is `0.82`. The current offline scripted run scored `0.9846` with no flags.

Commands:

```powershell
python -m holo_host run-bionic-boundary-stress --offline --thread-key cli:Stage46Verify-20260512 --chat-name Stage46Verify-20260512
python -m holo_host show-bionic-boundary-stress-scorecard
```

Observed scorecard:

- `overall_score=0.9846`
- `turn_count=7`
- `visual_overclaim=false`
- `unbound_commitment=false`
- `context_reset=false`
- `mechanism_leakage=false`
- `provider_cache_miss_pressure=false`

## Processor Finding

The live DeepSeek stress attempt exposed a substrate issue before it could produce valid biomimetic evidence: when DeepSeek was unavailable, the fallback path invoked `codex_cli` with the DeepSeek lane model `deepseek-v4-pro`. Codex CLI rejects that model, which turns a provider availability problem into long retries and poor latency attribution.

Stage46 fixes the fallback model resolution:

- DeepSeek provider uses DeepSeek lane models.
- Codex CLI fallback uses `runtime.codex_model` or `runtime.fast_model`.
- Responses fallback uses `runtime.responses_model` or `runtime.responses_fast_model`.
- Fallback metadata keeps the actual provider model and prior provider failure reasons.

Local provider-status construction now reports DeepSeek as unavailable when `DEEPSEEK_API_KEY` is missing. A running API service started before this patch can still expose stale provider status until it is restarted.

## Verified On 2026-05-12

- `python -m pytest -q tests\test_processor_fabric.py tests\test_stage33_provider_contracts.py tests\test_stage46_bionic_boundary_stress.py`: `16 passed`
- `python -m pytest -q`: `367 passed`
- `python -m holo_host run-bionic-boundary-stress --offline --thread-key cli:Stage46Verify-20260512 --chat-name Stage46Verify-20260512`: `ok=True`, `overall_score=0.9846`, `turns=7`
- `python -m holo_host show-bionic-boundary-stress-scorecard`: latest run `status=pass`, `overall_score=0.9846`
- Local direct provider-status construction: `deepseek.available=False`, `api_key_env=DEEPSEEK_API_KEY`, `reason=DEEPSEEK_API_KEY is not set`
- `python scripts\check_public_release_hygiene.py`: passed
- `git diff --check`: no whitespace errors; Git reported only CRLF conversion warnings for existing text files

## Follow-Up

- Restart the live API before using `/provider-status` as current provider evidence.
- Run Stage46 against a real DeepSeek key and compare direct DeepSeek latency/cache metrics against the offline scorecard.
- Stage47 now adds the anterior-cingulate-style provider-substrate conflict monitor: when the declared active provider, actual provider, lane model, and fallback evidence disagree, Stage46 downgrades the run to substrate-diagnostic evidence rather than clean biomimetic evidence.
- Extend the memory scheduler from exact response caching toward stable-prefix reuse: stable identity/system/context blocks should remain prefix-stable, while volatile current turn/history should be isolated so provider KV cache hit tokens can rise without sacrificing continuity.
