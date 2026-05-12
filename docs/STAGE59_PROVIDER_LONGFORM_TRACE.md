# Stage59 Provider Long-Form Trace

Stage59 turns the request for large-scale biomimetic dialogue into an operator-gated provider trace workflow.

The goal is not to burn tokens blindly. The goal is to collect real provider evidence through Holo's subject runtime with explicit budgets, provider/model provenance, per-turn journals, and geometry-calibration artifacts.

## Boundary

- Default mode is dry-run. It writes a plan and artifacts without calling any provider.
- Real provider calls require `--execute`.
- Provider fallback is disabled by default for strict traces. If DeepSeek fails, the run stops instead of silently switching to Codex CLI or another backend.
- Execute mode defaults to a shadow runtime rooted next to the output artifact. This prevents synthetic simulation turns from writing into live Holo memory or live Mind Graph state.
- Live runtime state requires explicit `--use-live-state`.
- The workflow does not start WeChat, widen transport rights, expose Holo as a downstream MCP server, mutate policy, add a second decision layer, or add an unbounded loop.

## Command

Dry-run plan:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --runs 2 --turns 8 --max-total-tokens 12000 --provider-hint deepseek --model deepseek-v4-pro --output artifacts\stage59\stage59_plan.html
```

Small strict DeepSeek smoke:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --runs 1 --turns 2 --max-total-tokens 8000 --provider-hint deepseek --model deepseek-v4-flash --lane micro_fast --max-output-tokens 80 --output artifacts\stage59\stage59_smoke_shadow.html
```

Large collection uses the same command shape with larger `--runs`, `--turns`, and `--max-total-tokens`. Keep `--output` unique per run so the HTML/JSON/PNG, turn journal, and shadow runtime remain paired.

## Artifacts

Each run writes:

- HTML report.
- Full JSON report.
- PNG provider-token dashboard.
- Execute-only JSONL turn journal.
- Execute-only shadow runtime directory unless `--use-live-state` is specified.
- Resume support through `--resume`, which reads the existing turn journal and continues from the next missing turn instead of replaying completed calls.

The JSON report carries:

- `provider_provenance`: requested and actual provider/model/lane, journal path, and state-isolation mode.
- `provider_trace_set`: planned and collected run/turn counts.
- `budget_guard`: observed tokens, remaining tokens, and stop reason.
- `stage46_compatible_runs`: trace payloads that can feed Stage57 geometry calibration.
- `stage57_calibration`: lifted geometry calibration over collected traces.
- `provider_evidence_gate`: conservative claim gate. It keeps `do_not_claim_real_manifold=true` until real provider trace depth and predictive gates are sufficient.

## Current Evidence

On 2026-05-13:

- Stage59 dry-run wrote `artifacts\stage59\stage59_plan.html`, `.json`, and `_provider_trace.png` with `planned_total_turns=16`, `real_provider_trace=false`, and `stopped_reason=dry_run_not_executed`.
- Strict DeepSeek shadow smoke wrote `artifacts\stage59\stage59_smoke_shadow_current.html`, `.json`, `_provider_trace.png`, and `_turns.jsonl`.
- The current smoke used `actual_providers=["deepseek"]`, `actual_models=["deepseek-v4-flash"]`, `state_isolation.mode=shadow_runtime`, `collected_turn_count=2`, and `observed_total_tokens=5301`.
- The smoke remained scientifically gated: Stage57 saw only `total_points=2`, so `do_not_claim_real_manifold=true`.

## Interpretation

Stage59 is the first real-provider bridge from high-intensity simulation into the consciousness-flow and geometry stack. It makes million-token runs operationally possible, but the acceptance condition remains evidence quality, not token volume.
