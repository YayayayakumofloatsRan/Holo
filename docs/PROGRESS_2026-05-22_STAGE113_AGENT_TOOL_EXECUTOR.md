# Progress 2026-05-22: Stage113 Agent Tool Executor

## Goal

Make provider tool proposals useful by executing allowlisted tools locally and
feeding observations back into the provider packet loop.

## Implemented

- Added `holo_host.stage113_agent_tool_executor`.
- Added `stage113-agent-tools` CLI.
- Added local execution for:
  - `external_lookup`
  - `memory_recall`
- Added Bing HTML fallback for live `external_lookup` when DuckDuckGo HTML is
  unavailable or times out.
- Added skipped/rejected handling for unknown or disallowed calls.
- Added reentry contract for Stage107 `tool_observations`.
- Added deterministic tests for:
  - executing accepted tool calls;
  - skipping rejected tool calls;
  - local memory recall;
  - external lookup through an injected backend;
  - Stage107 observation reentry;
  - CLI memory recall.

## Evidence

RED:

```powershell
python -m pytest -q tests\test_stage113_agent_tool_executor.py --basetemp .holo_runtime\pytest-stage113-red
```

Observed:

- `ModuleNotFoundError: No module named 'holo_host.stage113_agent_tool_executor'`

GREEN:

```powershell
python -m pytest -q tests\test_stage113_agent_tool_executor.py --basetemp .holo_runtime\pytest-stage113-green
```

Observed:

- `3 passed`

CLI memory execution:

```powershell
python -m holo_host stage113-agent-tools --tool memory_recall --query "provider packet continuity"
```

Observed:

- `stage=113`
- `executed_count=1`
- `tool=memory_recall`
- `status=ok`

CLI live external lookup:

```powershell
python -m holo_host stage113-agent-tools --tool external_lookup --query "DeepSeek API status" --live-network
```

Observed:

- `stage=113`
- `executed_count=1`
- `tool=external_lookup`
- `status=ok`
- `results=3`

## Boundary

The provider may propose tools, but local Holo executes them. This keeps
authority and side effects inside the local brain while still making the agent
able to act with tools.
