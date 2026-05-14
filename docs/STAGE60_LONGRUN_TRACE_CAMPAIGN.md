# Stage60 Long-Run Trace Campaign

Stage60 turns Stage59's single provider trace into a recoverable campaign layer.

The goal is workflow continuity: run the same bionic perturbation program across multiple DeepSeek models, keep every cell isolated and resumable, preserve evidence while Codex sessions can disconnect, and make "major breakthrough" claims pass through a conservative gate instead of operator intuition.

## Boundary

- Default mode is dry-run. It writes campaign and per-cell artifacts without provider calls.
- Real provider calls require `--execute`.
- Each executed cell defaults to its own shadow runtime directory. Live runtime state requires explicit `--use-live-state`.
- Provider fallback remains disabled by default through Stage59 strict provider traces.
- Each model cell has its own output directory, turn journal, Stage59 HTML/JSON/PNG, and optional shadow runtime.
- The campaign writes `campaign_manifest.json` after every cell and `campaign_events.jsonl` as an append-only continuity log.
- The workflow does not start WeChat, widen transport rights, expose Holo as a downstream MCP server, mutate policy, add a second decision layer, or add an unbounded loop.

## Command

Dry-run campaign:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --campaign-id stage60_plan --models deepseek-v4-pro,deepseek-v4-flash --runs-per-model 1 --turns 8 --max-total-tokens-per-cell 12000 --output-root artifacts\stage60\stage60_plan
```

Small strict DeepSeek shadow smoke:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --execute --campaign-id stage60_smoke_shadow --models deepseek-v4-pro,deepseek-v4-flash --runs-per-model 1 --turns 1 --max-total-tokens-per-cell 7000 --max-output-tokens 80 --output-root artifacts\stage60\stage60_smoke_shadow
```

Long campaigns use the same command shape with larger `--runs-per-model`, `--turns`, and `--max-total-tokens-per-cell`. Keep the campaign id and output root stable to resume after interruption; use `--no-resume` only when intentionally starting a fresh campaign event log.

## Artifacts

Campaign-level artifacts:

- `campaign.html`
- `campaign.json`
- `campaign_campaign.png`
- `campaign_manifest.json`
- `campaign_events.jsonl`

Per-cell artifacts under `cells\<index>_<model>\`:

- Stage59 provider trace HTML.
- Stage59 full JSON report.
- Stage59 provider-token PNG.
- Execute-only `provider_trace_turns.jsonl`.
- Execute-only `shadow_runtime\` unless `--use-live-state` is specified.

## Evidence Gate

Stage60 keeps `do_not_claim_major_breakthrough=true` unless all of the following are true:

- At least two real provider cells exist.
- At least 48 real provider turns have been collected.
- At least two cells pass Stage57 predictive gates.
- At least two cells satisfy trace-depth gates.
- Top bionic stability score is at least `0.82`.
- Aggregate prompt-cache hit ratio is at least `0.2`.
- No cell still carries `do_not_claim_real_manifold=true`.

This is deliberately stricter than the smoke test. A campaign can prove the workflow, provider path, and continuity guarantees without proving a consciousness manifold.

## Current Evidence

On 2026-05-13:

- Dry-run wrote `artifacts\stage60\stage60_plan\campaign.html`, `.json`, `_campaign.png`, `campaign_manifest.json`, `campaign_events.jsonl`, and two per-model Stage59 dry-run cells. It reported `planned_cell_count=2`, `planned_total_turns=16`, `real_provider_cell_count=0`, and `do_not_claim_major_breakthrough=true`.
- Strict DeepSeek shadow smoke wrote `artifacts\stage60\stage60_smoke_shadow\campaign.html`, `.json`, `_campaign.png`, `campaign_manifest.json`, `campaign_events.jsonl`, two per-model Stage59 reports, two per-cell turn journals, and two per-cell shadow runtimes.
- The original smoke used `actual_providers=["deepseek"]`, `actual_models=["deepseek-v4-flash","deepseek-v4-pro"]`, `real_provider_cell_count=2`, `collected_turn_count=2`, `observed_total_tokens=5128`, and aggregate prompt-cache hit ratio `0.252117`. Current defaults are now pro-first for capability validation.
- The smoke remained scientifically gated: the trace is only two turns, no cell passed Stage57 predictive or trace-depth gates, and `do_not_claim_major_breakthrough=true`.

## Interpretation

Stage60 is a workflow-continuity breakthrough, not a consciousness-manifold claim. Holo can now run recoverable, multi-model, shadow-state, real-provider bionic campaigns with inspectable token budgets and cross-model ranking. The next empirical breakthrough requires enough real trace depth for Stage57 rather than more orchestration code.
