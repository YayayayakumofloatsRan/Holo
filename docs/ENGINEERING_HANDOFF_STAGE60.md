# Engineering Handoff Stage60

## Summary

Stage60 implements a recoverable long-run provider trace campaign orchestrator.

Stage59 proved that one strict DeepSeek provider trace can pass through Holo's subject runtime, journal every turn, and feed Stage57 geometry calibration. Stage60 lifts that into a campaign controller: each model/lane cell gets isolated output, an optional shadow runtime, Stage59 artifacts, a turn journal, campaign-level manifest/events, cross-model ranking, and a conservative major-breakthrough gate.

## Boundary

- Dry-run remains the default and performs no provider call.
- `--execute` is required for provider token consumption.
- Execute mode uses one shadow runtime per campaign cell unless `--use-live-state` is explicitly passed.
- Stage59 strict provider behavior still disables fallback by default.
- Campaign orchestration is observational only. It does not start WeChat, expose Holo as a downstream MCP server, widen transport authority, grant runtime decision authority, write live self-memory by default, mutate policy, add a second decision layer, or add an unbounded loop.

## Files

- `holo_host/consciousness_trace_campaign.py`
  - Adds `run_provider_trace_campaign()`.
  - Splits a campaign into model cells, infers lanes (`flash` to `micro_fast`, default to `subject_main`), and calls Stage59 for each cell.
  - Writes `campaign_manifest.json` after every cell and append-only `campaign_events.jsonl`.
  - Aggregates planned turns, collected turns, observed tokens, provider/model provenance, prompt-cache hit ratio, Stage57 evidence gates, and top model ranking.
  - Writes campaign HTML/JSON/PNG through `write_provider_trace_campaign_artifacts()`.
- `holo_host/cli.py`
  - Adds `run-consciousness-trace-campaign`.
- `tests/test_stage60_trace_campaign.py`
  - Covers dry-run manifest/events, execute resume/path handoff, campaign HTML/JSON/PNG, and CLI dry-run.
- `docs/STAGE60_LONGRUN_TRACE_CAMPAIGN.md`
  - Operator workflow, artifacts, evidence gate, and current interpretation.

## Verification

- `python -m pytest -q tests\test_stage60_trace_campaign.py`: `4 passed`
- `python -m py_compile holo_host\consciousness_trace_campaign.py holo_host\cli.py`: passed
- `python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --campaign-id stage60_plan --models deepseek-v4-flash,deepseek-v4-pro --runs-per-model 1 --turns 8 --max-total-tokens-per-cell 12000 --output-root artifacts\stage60\stage60_plan`: returned `status=dry_run`, `planned_cell_count=2`, `planned_total_turns=16`, `real_provider_cell_count=0`, and `do_not_claim_major_breakthrough=true`
- `python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --execute --campaign-id stage60_smoke_shadow --models deepseek-v4-flash,deepseek-v4-pro --runs-per-model 1 --turns 1 --max-total-tokens-per-cell 7000 --max-output-tokens 80 --output-root artifacts\stage60\stage60_smoke_shadow`: returned `status=complete`, `real_provider_cell_count=2`, `collected_turn_count=2`, `observed_total_tokens=5128`, `top_model=deepseek-v4-flash`, `top_score=0.9037`, and `do_not_claim_major_breakthrough=true`
- `python -m pytest -q tests\test_stage60_trace_campaign.py tests\test_stage59_provider_trace.py tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py tests\test_processor_fabric.py`: `57 passed`
- `python -m py_compile holo_host\consciousness_trace_campaign.py holo_host\consciousness_provider_trace.py holo_host\codex_runner.py holo_host\cli.py`: passed
- `python -m pytest -q`: `438 passed`
- `python scripts\check_public_release_hygiene.py`: passed
- `git diff --check`: no whitespace errors; Git emitted only CRLF conversion warnings for existing text files

## Current Artifact Paths

- `artifacts\stage60\stage60_plan\campaign.html`
- `artifacts\stage60\stage60_plan\campaign.json`
- `artifacts\stage60\stage60_plan\campaign_campaign.png`
- `artifacts\stage60\stage60_plan\campaign_manifest.json`
- `artifacts\stage60\stage60_plan\campaign_events.jsonl`
- `artifacts\stage60\stage60_smoke_shadow\campaign.html`
- `artifacts\stage60\stage60_smoke_shadow\campaign.json`
- `artifacts\stage60\stage60_smoke_shadow\campaign_campaign.png`
- `artifacts\stage60\stage60_smoke_shadow\campaign_manifest.json`
- `artifacts\stage60\stage60_smoke_shadow\campaign_events.jsonl`
- `artifacts\stage60\stage60_smoke_shadow\cells\01_deepseek-v4-flash\provider_trace_turns.jsonl`
- `artifacts\stage60\stage60_smoke_shadow\cells\02_deepseek-v4-pro\provider_trace_turns.jsonl`

## Interpretation

The verified smoke is intentionally tiny. It proves the recoverable campaign controller, multi-model strict DeepSeek path, per-cell shadow isolation, per-cell journal handoff, campaign manifest/event continuity, cross-model ranking, and conservative breakthrough gating. It does not prove a real consciousness manifold because only two provider turns were collected.

## Next Work

- Run a budget-approved Stage60 campaign with at least 48 real provider turns across at least two model cells.
- Keep the output root stable and default resume enabled so interruption does not replay completed turns.
- Use Stage57/60 gates as the claim boundary: if any cell still carries `do_not_claim_real_manifold=true`, do not call it a manifold breakthrough.
