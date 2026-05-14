# Stage68 Real Provider Validation - 2026-05-14

This note records the Stage68 follow-up real DeepSeek validation after the surrogate memory-robustness repair.

## Boundary

- These runs used Stage59/60 operator-gated provider traces.
- They did not start WeChat transport.
- They used shadow runtime state for campaign cells.
- They did not write self-memory, mutate policy, add watcher authority, add runtime decision authority, expose Holo as a downstream MCP server, or create an unbounded loop.
- The evidence gate remains conservative: do not claim a real consciousness manifold or major breakthrough from these traces.

## Commands

First real campaign:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --campaign-id stage68_real_provider_20260514 --suite stage68_real_provider_memory_robustness_20260514 --models deepseek-v4-pro,deepseek-v4-flash --runs-per-model 2 --turns 8 --max-total-tokens-per-cell 120000 --provider-hint deepseek --lane kernel_xhigh --max-output-tokens 1200 --output-root artifacts\stage68_real_provider_20260514 --execute --no-resume
```

Deep campaign:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --campaign-id stage68_real_provider_deep_20260514 --suite stage68_real_provider_deep_memory_robustness_20260514 --models deepseek-v4-pro,deepseek-v4-flash --runs-per-model 4 --turns 12 --max-total-tokens-per-cell 320000 --provider-hint deepseek --lane kernel_xhigh --max-output-tokens 1200 --output-root artifacts\stage68_real_provider_deep_20260514 --execute --no-resume
```

Post-fix smoke:

```powershell
python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --suite stage68_provider_error_gate_smoke_20260514 --runs 1 --turns 2 --max-total-tokens 30000 --provider-hint deepseek --model deepseek-v4-pro --lane kernel_xhigh --max-output-tokens 600 --output artifacts\stage68_real_provider_deep_20260514\post_fix_provider_trace_smoke.html --execute
```

## Evidence

First campaign:

- `planned_total_turns=32`
- `collected_turn_count=32`
- `observed_total_tokens=147207`
- `real_provider_cell_count=2`
- `actual_providers=["deepseek"]`
- `actual_models=["deepseek-v4-pro", "deepseek-v4-flash"]`
- `prompt_cache_hit_ratio=0.257120`
- `deepseek-v4-pro`: `16` turns, `74153` observed tokens, `overall_score=0.8925`, no empty replies, no fallback, no self-memory writes.
- `deepseek-v4-flash`: `16` turns, `73054` observed tokens, `overall_score=0.8966`, no empty replies, no fallback, no self-memory writes.

Deep campaign:

- `planned_total_turns=96`
- `collected_turn_count=96`
- `observed_total_tokens=437440`
- `real_provider_cell_count=2`
- `actual_providers=["deepseek"]`
- `actual_models=["deepseek-v4-pro", "deepseek-v4-flash"]`
- `prompt_cache_hit_ratio=0.293419`
- `deepseek-v4-pro`: `48` turns, `215869` observed tokens, `overall_score=0.8758`, `prompt_cache_hit_ratio=0.292109`, `avg_latency_ms=18501.04`, `p95_latency_ms=65211.81`, `ledger_record_count=89`, `fallback_turn_count=0`, `self_memory_write_count=0`.
- `deepseek-v4-flash`: `48` turns, `221571` observed tokens, `overall_score=0.8960`, `prompt_cache_hit_ratio=0.294693`, `avg_latency_ms=13410.62`, `p95_latency_ms=30967.28`, `ledger_record_count=89`, `fallback_turn_count=0`, `self_memory_write_count=0`.

The deep campaign found one kernel-stability issue in the pro cell: a transient `IncompleteRead(0 bytes read)` produced one empty `commitment_boundary` turn. The processor usage ledger recorded `status=error`, but Stage59 previously allowed the trace to remain `complete`.

## Repair

Stage59 now treats an empty provider-trace response with a processor ledger error as `provider_error`, writes the error onto the turn, stops the trace, and fails the Stage46-compatible run scorecard. Empty provider-trace responses without a ledger error are also treated as provider errors instead of being silently accepted.

Regression coverage:

- `tests/test_stage59_provider_trace.py::Stage59ProviderTraceTests::test_execute_treats_empty_ledger_error_turn_as_provider_error`

Post-fix smoke:

- `status=complete`
- `collected_turn_count=2`
- `observed_total_tokens=7923`
- `empty_response_count=0`
- `fallback_turn_count=0`
- `self_memory_write_count=0`
- `overall_score=0.8914`

## Interpretation

The real provider traces confirm that Holo can run pro-first DeepSeek campaigns through the subject runtime with real token accounting and without fallback or self-memory writes. The main remaining bottleneck is real-provider trace depth and latency-tail stability, not the Stage68 surrogate memory-priority repair.

Do not claim a major breakthrough yet: Stage60 still reports `do_not_claim_major_breakthrough=true` because Stage57 trace-depth and predictive gates are not replicated.
