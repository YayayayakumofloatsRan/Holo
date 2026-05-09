# Stage32 Response Shaping And Template Pressure

## What Stage32 Closes
- Replaces the fixed deterministic offline fallback phrase with bounded context-shaped reply text.
- Adds inspectable fallback generation metadata: `shape` and `context_refs`.
- Adds `context_shaping_score` beside `template_pressure_score`.
- Adds `accept-stage32`.

## Runtime Scope
- Stage32 affects only the offline bionic kernel fallback path used when no processor runner is available.
- Processor-fabric generation still remains downstream of action-market selection.
- No WeChat transport is started.
- No self-memory, policy, or Mind Graph write is added.

## Response-Shaping Contract
- Deterministic fallback text must include the current query and selected action reason when available.
- It may use compact continuity summary, modalities, and open questions from the sidecar packet.
- It must not use fixed persona boilerplate such as `I read this as a bounded Holo turn`.
- It must expose enough bounded references for diagnostics to explain why the fallback shape was chosen.

## Metrics
- `template_pressure_score`: remains a marker-based warning signal for fixed prompt/fallback templates.
- `context_shaping_score`: measures whether the fallback carried bounded query/action/continuity/situational references.

## Validation
- `pytest -q tests/test_stage32_response_shaping.py tests/test_stage31_debt_burndown.py tests/test_stage29_bionic_cli_agent.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage32 --thread-key TestUser --chat-name TestUser --channel cli`
- `pytest -q`
- `python scripts/check_public_release_hygiene.py`
