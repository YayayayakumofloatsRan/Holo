# Stage227 Web Provider Registry

Kernel version remains `2.1.0`.

## Purpose

Stage226 created the web research kernel contract. Stage227 adds the provider
layer needed to make search execution observable and bounded.

The goal is to avoid treating a single hard-coded search page as the system
architecture. Search is now:

```text
SearchGoal/SearchPlan -> provider registry -> bounded provider attempt
-> domain filter -> web observation -> provider health
```

## Runtime Additions

`holo_agent.web_providers` adds:

- `SearchProvider`
- `SearchAttempt`
- `SearchProviderRegistry`
- `domain_allowed()`
- `filter_results_by_domain()`

Provider attempts are run with a per-provider timeout. A slow provider records
`status=timeout` and the registry can fall back to the next provider.

## Health

Provider health schema:

```text
holo.web_provider_health.v1
```

It records:

- `network_enabled`
- `providers`
- `last_status`
- `last_error`
- `attempts[]`

The health report is attached to:

- `web_search` observations
- final agent metadata as `web_provider_health`
- `python -m holo_agent status`
- interactive `/web`

## Source Policy

`web_search` now accepts optional:

- `allowed_domains`
- `blocked_domains`
- `region`

When a model-selected query matches the active `SearchPlan`, the host enriches
the tool arguments with the planned domain policy. This keeps the model in
charge of choosing the action while the host enforces the source policy.

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage227_web_provider_layer.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage227-targeted2
```

Result:

```text
6 passed
```

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage227-full4
```

Result:

```text
56 passed
```

WSL live smoke:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo-agent-kernel && python3 -m holo_agent run 'Find official OpenAI Codex CLI docs and cite sources' --trace --model fallback --max-steps 6 --log .holo_kernel/stage227-wsl-live3.jsonl"
```

Result:

```text
web_search was attempted but failed: provider_timeout
```

This is a bounded failure, not a hang. The next stage should add stronger
provider backends or environment-specific WSL network diagnostics.
