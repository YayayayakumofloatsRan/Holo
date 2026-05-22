# Progress 2026-05-22: Stage114 Agent Tool Cycle

## Goal

Move from standalone tool execution to a closed agent tool loop.

## Implemented

- Added `holo_host.stage114_agent_tool_cycle`.
- Added `stage114-agent-tool-cycle` CLI.
- Added provider `tool_calls` parsing through Stage106.
- Added local execution through Stage113.
- Added Stage107 reentry with `tool_observation`.
- Added `next_provider_packet` extraction so the next provider call has the
  observation summary in inputs.
- Supports both:
  - provider-proposed tool calls;
  - Stage105 `tool_first` requests.

## Evidence

RED:

```powershell
python -m pytest -q tests\test_stage114_agent_tool_cycle.py --basetemp .holo_runtime\pytest-stage114-red
```

Observed:

- `ModuleNotFoundError: No module named 'holo_host.stage114_agent_tool_cycle'`

GREEN:

```powershell
python -m pytest -q tests\test_stage114_agent_tool_cycle.py --basetemp .holo_runtime\pytest-stage114-green
```

Observed:

- `3 passed`

## Boundary

Stage114 still uses simulated provider tool calls in CLI. It exercises the same
surface a live DeepSeek response uses: `choices[].message.tool_calls`. A later
live-provider stage can feed the actual DeepSeek response into the same cycle.
