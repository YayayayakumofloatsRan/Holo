# Engineering Handoff Stage59

## Summary

Stage59 implements an operator-gated real provider long-form trace runner.

Stage58 proved the geometry toolchain can process long surrogate traces. Stage59 moves the next step into real provider evidence while preserving Holo's boundaries: provider calls stay inside the processor fabric, fallback is disabled by default for strict DeepSeek traces, execute mode uses a shadow runtime by default, and all outputs are journaled and artifact-backed.

## Boundary

- Dry-run is the default and performs no provider call.
- `--execute` is required for provider token consumption.
- Strict provider traces set `disable_provider_fallback`; DeepSeek failures stop the run instead of falling through to Codex CLI.
- Execute mode uses a shadow runtime unless `--use-live-state` is explicitly passed.
- No WeChat transport is started.
- No downstream Holo MCP server, transport authority, runtime decision authority, self-memory write path, policy mutation, second decision layer, or unbounded loop is added.

## Files

- `holo_host/consciousness_provider_trace.py`
  - Adds `run_provider_longform_trace()`.
  - Adds `HoloReplyTurnExecutor` and `ForcedProviderRunner` so real traces pass through Holo's subject runtime while enforcing provider/model/lane/output caps.
  - Adds `shadow_config_for_provider_trace()` for synthetic-trace state isolation.
  - Writes HTML/JSON/PNG artifacts and execute-mode JSONL turn journals.
  - Supports `--resume` by reading existing turn journals and continuing from the next missing turn.
  - Emits Stage46-compatible run payloads and feeds them into Stage57 calibration.
- `holo_host/codex_runner.py`
  - Adds `disable_provider_fallback` request metadata support for strict provider evidence.
- `holo_host/cli.py`
  - Adds `run-consciousness-provider-trace`.
- `tests/test_stage59_provider_trace.py`
  - Covers dry-run gating, budget stop behavior, journal/artifact export, strict-provider no-fallback behavior, shadow runtime redirection, and CLI dry-run.
- `docs/STAGE59_PROVIDER_LONGFORM_TRACE.md`
  - Operator workflow and interpretation.

## Verification

- `python -m pytest -q tests\test_stage59_provider_trace.py`: `7 passed`
- `python -m py_compile holo_host\consciousness_provider_trace.py holo_host\codex_runner.py holo_host\cli.py`: passed
- `python -m pytest -q tests\test_stage59_provider_trace.py tests\test_processor_fabric.py`: `21 passed`
- `python -m pytest -q tests\test_stage59_provider_trace.py tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py tests\test_processor_fabric.py`: `53 passed`
- `python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --runs 2 --turns 8 --max-total-tokens 12000 --provider-hint deepseek --model deepseek-v4-pro --output artifacts\stage59\stage59_plan.html`: returned `status=dry_run`, `planned_total_turns=16`, `real_provider_trace=false`, and `stopped_reason=dry_run_not_executed`
- `python -m holo_host --config .holo_host.toml show-provider-substrate-status`: returned `ok=true`, `score=1.0`, `deepseek.available=true`, and `api_key_source=windows_registry`
- `python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --runs 1 --turns 2 --max-total-tokens 8000 --provider-hint deepseek --model deepseek-v4-flash --lane micro_fast --max-output-tokens 80 --output artifacts\stage59\stage59_smoke_shadow_current.html`: returned `status=complete`, `collected_turn_count=2`, `real_provider_trace=true`, `actual_providers=["deepseek"]`, `actual_models=["deepseek-v4-flash"]`, `state_isolation.mode=shadow_runtime`, `observed_total_tokens=5301`, `stopped_reason=completed`, and `do_not_claim_real_manifold=true`
- `git diff --check`: no whitespace errors; Git emitted only CRLF conversion warnings for existing text files
- `python scripts\check_public_release_hygiene.py`: passed
- `python -m pytest -q`: `434 passed`

## Current Artifact Paths

- `artifacts\stage59\stage59_plan.html`
- `artifacts\stage59\stage59_plan.json`
- `artifacts\stage59\stage59_plan_provider_trace.png`
- `artifacts\stage59\stage59_smoke_shadow_current.html`
- `artifacts\stage59\stage59_smoke_shadow_current.json`
- `artifacts\stage59\stage59_smoke_shadow_current_provider_trace.png`
- `artifacts\stage59\stage59_smoke_shadow_current_turns.jsonl`
- `artifacts\stage59\stage59_smoke_shadow_current_shadow_runtime\`

## Interpretation

The verified smoke is deliberately small. It proves the real DeepSeek path, strict provider provenance, shadow-state isolation, turn journaling, and Stage57 integration. It does not claim a consciousness manifold because only two real provider points were collected.

## Next Work

- Run a budget-approved long trace with enough points to satisfy Stage56/57 trace-depth gates.
- Compare `deepseek-v4-flash` and `deepseek-v4-pro` under the same Stage59 perturbation program.
- Keep large runs in shadow state unless an operator explicitly wants live-memory participation.
