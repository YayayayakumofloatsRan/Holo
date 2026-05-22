# Stage116 Fluent Agent Tool Loop

## Purpose

Stage116 upgrades Stage115 from a single tool-return cycle into a fluent
multi-round agent loop. The goal is closer to Codex-style tool use: the model
may request one tool, inspect the observation, request another tool, and only
then produce the final answer.

## Runtime Contract

When `auto_execute_provider_tools=true`, `DeepSeekProvider` now:

1. sends the initial user packet with allowlisted tool schemas;
2. parses provider `tool_calls`;
3. executes accepted local tools through Stage113;
4. returns one `role=tool` message for every tool call;
5. keeps `tool_choice=auto` while the loop has budget left;
6. repeats until the provider returns a non-tool final answer or budget is
   exhausted.

Budget defaults:
- `max_provider_tool_rounds = 4`
- `max_provider_tool_calls = 16`

Both can be overridden through `ProcessorTaskRequest.metadata`.

## Rejection Handling

Rejected calls are no longer silent. Unknown tools, invalid argument payloads,
or budget-exceeded calls are converted into `role=tool` observations with
`status = rejected`. This lets the provider recover and answer within the
allowed surface instead of leaving Holo with an empty tool-call turn.

## Observability

The result metadata now reports:
- `agent_tool_loop.round_count`
- `agent_tool_loop.rounds[*].tool_names`
- `agent_tool_loop.executed_count`
- `agent_tool_loop.skipped_count`
- `agent_tool_loop.tool_call_count`
- `agent_tool_loop.exhausted`
- combined usage across all provider packets

This is the operational substrate needed to debug whether Holo is actually
using tools skillfully or merely exposing schemas.

## Verification

Primary regression:

```powershell
python -m pytest -q tests\test_stage116_multiround_agent_tools.py --basetemp .holo_runtime\pytest-stage116-green
```

Expected result:
- a first provider tool call can trigger a second provider tool call before
  final answer commitment;
- `tool_choice=auto` remains active while budget remains;
- rejected tool calls become explicit local tool observations;
- usage is summed across all provider packets.
