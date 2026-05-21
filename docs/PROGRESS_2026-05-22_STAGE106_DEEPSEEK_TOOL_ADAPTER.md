# Progress 2026-05-22: Stage106 DeepSeek Tool Adapter

## Goal

Adapt Holo to DeepSeek v4-class tool-calling without giving the provider direct
execution authority.

## Implemented

- Added `holo_host.stage106_deepseek_tool_adapter`.
- Added allowlisted OpenAI/DeepSeek-compatible tool schema generation.
- Added provider `tool_calls` parsing and validation.
- Wired `DeepSeekProvider` to attach tools only when explicitly enabled by
  request metadata.
- Added `stage106-deepseek-tool-adapter` CLI dry-run inspection.
- Added focused Stage106 tests.

## Boundary

The current release exposes and parses provider tool calls. It does not execute
tools automatically. Execution must stay in a later Holo-controlled WSL tool
loop that validates permissions, runs the read-only or external lookup tool,
and compresses the observation into the next Stage105 packet.

## Verification

```powershell
python -m pytest -q tests\test_stage106_deepseek_tool_adapter.py --basetemp .holo_runtime\pytest-stage106-green
```

Observed:

- `6 passed`
