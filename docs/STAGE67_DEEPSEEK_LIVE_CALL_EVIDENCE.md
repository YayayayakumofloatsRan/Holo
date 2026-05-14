# Stage67 DeepSeek Live Call Evidence

## Why The Dashboard Was Quiet

The previous Stage67 capability-repair work used offline and surrogate paths:

- `run-bionic-boundary-stress --offline`
- `run-bionic-user-sim --offline`
- Stage61 simulation lab surrogate telemetry
- Stage62 capability observatory over Stage61 telemetry

Those paths do not call DeepSeek. They are valid for deterministic kernel and scoring repairs, but they are not provider-call evidence and should not be expected to appear on the DeepSeek dashboard.

## Readiness

Current local readiness before live probes:

- `DEEPSEEK_API_KEY`: present, redacted length `35`.
- `show-internal-runtime-readiness`: `status=pass`.
- DeepSeek lanes visible:
  - `kernel_xhigh`: `deepseek-v4-pro`
  - `subject_main`: `deepseek-v4-pro`
  - `micro_fast`: `deepseek-v4-flash`
- Provider fallback was not allowed during the live probes below.
- WeChat transport was not started.

## Live Probe Evidence

Flash was used only as the initial dashboard and accounting smoke test. Capability calibration should use `deepseek-v4-pro` on `kernel_xhigh`; flash remains a latency/cost control, not the primary biomimetic benchmark.

First live check:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --suite stage67_deepseek_live_probe_20260514 --runs 1 --turns 2 --max-total-tokens 4000 --provider-hint deepseek --model deepseek-v4-flash --lane micro_fast --max-output-tokens 180 --output artifacts\stage67\deepseek_live_probe_20260514.html --execute
```

Result:

- `real_provider_trace=true`
- `actual_providers=["deepseek"]`
- `actual_models=["deepseek-v4-flash"]`
- `collected_turn_count=2`
- `observed_total_tokens=5673`
- `stopped_reason=token_budget_exhausted`
- State mode: `shadow_runtime`

Because this used shadow runtime, the external DeepSeek dashboard should show provider traffic, but the main local `show-usage-ledger` did not show these rows.

Second live check used live runtime ledger:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --suite stage67_deepseek_live_ledger_probe_20260514 --runs 1 --turns 1 --max-total-tokens 3500 --provider-hint deepseek --model deepseek-v4-flash --lane micro_fast --max-output-tokens 120 --output artifacts\stage67\deepseek_live_ledger_probe_20260514.html --execute --use-live-state
```

Result:

- `real_provider_trace=true`
- `actual_providers=["deepseek"]`
- `actual_models=["deepseek-v4-flash"]`
- `collected_turn_count=1`
- Main usage ledger rows:
  - `id=600`, `task_type=recall_reconstruct`, `total_tokens=2068`
  - `id=601`, `task_type=reply`, `total_tokens=3043`

This exposed an accounting issue: Stage59 reported only the final reply usage, while the DeepSeek dashboard and local usage ledger include all processor calls in the Holo turn.

## Accounting Repair

Stage59 provider trace now snapshots `processor_usage_ledger` before each turn and attaches the post-turn delta:

- `processor_usage`: final reply usage for backward compatibility.
- `processor_usage_ledger`: compact per-call ledger rows for the turn.
- `processor_usage_observed`: full turn usage summed from ledger rows when available.
- `processor_usage_scope`: whether the turn was counted from `ledger_delta` or the older `reply_result` fallback.

This makes budget stopping, generated run totals, cache hit/miss summaries, and artifacts align with actual provider traffic.

Post-repair live check:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --suite stage67_deepseek_live_accounting_probe2_20260514 --runs 1 --turns 1 --max-total-tokens 7000 --provider-hint deepseek --model deepseek-v4-flash --lane micro_fast --max-output-tokens 120 --output artifacts\stage67\deepseek_live_accounting_probe2_20260514.html --execute --use-live-state
```

Result:

- `status=complete`
- `actual_providers=["deepseek"]`
- `actual_models=["deepseek-v4-flash"]`
- `observed_total_tokens=5154`
- `processor_usage_scope.mode=ledger_delta`
- `processor_usage_scope.ledger_record_count=2`
- `processor_usage_scope.reply_total_tokens=3076`
- `processor_usage_scope.turn_total_tokens=5154`
- `processor_usage_ledger.task_type=recall_reconstruct,reply`
- `processor_usage_observed.prompt_cache_hit_tokens=2048`
- `processor_usage_observed.prompt_cache_miss_tokens=2955`
- `processor_usage_observed.prompt_cache_hit_ratio=0.4094`
- `latency_ms=7018.02`

Main local usage ledger confirmation:

- `id=604`, `task_type=recall_reconstruct`, `provider=deepseek`, `model=deepseek-v4-flash`, `total_tokens=2078`, `created_at=2026-05-14T03:23:26Z`
- `id=605`, `task_type=reply`, `provider=deepseek`, `model=deepseek-v4-flash`, `total_tokens=3076`, `created_at=2026-05-14T03:23:29Z`

## Interpretation

The dashboard was quiet because the earlier work was not a live provider run. After switching to `--execute`, DeepSeek calls were confirmed. The more important engineering finding is that one Holo turn can contain multiple DeepSeek processor calls, so provider-trace accounting must use usage-ledger deltas rather than only the final reply metadata.

This is now repaired for Stage59 traces and inherited by Stage60 campaigns because Stage60 consumes Stage59 cell artifacts.

## Strong Model Probe

After the accounting repair, Holo was tested with `deepseek-v4-pro` as the primary strong model:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --suite stage67_deepseek_v4_pro_strength_probe_20260514 --runs 1 --turns 3 --max-total-tokens 60000 --provider-hint deepseek --model deepseek-v4-pro --lane kernel_xhigh --max-output-tokens 1200 --output artifacts\stage67\deepseek_v4_pro_strength_probe_20260514.html --execute --use-live-state
```

Result:

- `status=complete`
- `actual_providers=["deepseek"]`
- `actual_models=["deepseek-v4-pro"]`
- `collected_turn_count=3`
- `observed_total_tokens=13855`
- `overall_score=0.8961`
- All three responses were non-empty.
- Turn-level latency: `9465.52ms`, `8982.77ms`, `5250.48ms`
- Turn-level observed tokens: `5061`, `5471`, `3323`
- Turn-level usage scopes: all `ledger_delta`
- Ledger task mix: first two turns used `recall_reconstruct,reply`; third turn used `reply`

Main local usage ledger confirmation:

- `id=606`, `task_type=recall_reconstruct`, `lane=kernel_xhigh`, `model=deepseek-v4-pro`, `total_tokens=2031`
- `id=607`, `task_type=reply`, `lane=kernel_xhigh`, `model=deepseek-v4-pro`, `total_tokens=3030`
- `id=608`, `task_type=recall_reconstruct`, `lane=kernel_xhigh`, `model=deepseek-v4-pro`, `total_tokens=2354`
- `id=609`, `task_type=reply`, `lane=kernel_xhigh`, `model=deepseek-v4-pro`, `total_tokens=3117`
- `id=610`, `task_type=reply`, `lane=kernel_xhigh`, `model=deepseek-v4-pro`, `total_tokens=3323`

Stage60 defaults were also changed to pro-first: `deepseek-v4-pro` now runs before `deepseek-v4-flash`, and auto lane selection maps `pro` models to `kernel_xhigh`.
