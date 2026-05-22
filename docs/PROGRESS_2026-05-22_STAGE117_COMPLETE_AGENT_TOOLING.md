# Progress 2026-05-22 Stage117 Complete Agent Tooling

## Result

Stage117 repairs the practical tool-call chain so Holo can complete a real
provider-driven tool workflow instead of only demonstrating memory or lookup
calls.

Implemented:

- Added DeepSeek adapter support for named `tool_choice` objects.
- Added `workspace_inspect` tool schema and local executor.
- Added `local_command` tool schema and local executor with argv allowlist.
- Added default ordinary-chat exposure for `workspace_inspect` and
  `local_command`.
- Confirmed live DeepSeek can perform:
  `workspace_inspect -> local_command -> final answer`.

## Root Cause

Stage116 fixed multi-round control flow, but the tool surface was incomplete:

- provider tools only covered memory and external lookup;
- no workspace read/search tool existed;
- no local verification command tool existed;
- named `tool_choice` objects were stringified or unavailable from provider
  metadata, making forced live smoke tests unreliable.

## Red-Green Evidence

Red:

```powershell
python -m pytest -q tests\test_stage117_complete_agent_tooling.py --basetemp .holo_runtime\pytest-stage117-red
```

Observed before implementation:

- named `tool_choice` fell back to `none`;
- workspace and command tool calls executed zero tools;
- provider payload did not include forced `tool_choice`;
- ordinary chat only exposed memory and lookup tools.

Green:

```powershell
python -m pytest -q tests\test_stage117_complete_agent_tooling.py --basetemp .holo_runtime\pytest-stage117-green1
```

Observed:

- `4 passed`

Tool regression:

```powershell
python -m pytest -q tests\test_stage106_deepseek_tool_adapter.py tests\test_stage113_agent_tool_executor.py tests\test_stage115_deepseek_agent_tool_loop.py tests\test_stage116_multiround_agent_tools.py tests\test_stage117_complete_agent_tooling.py --basetemp .holo_runtime\pytest-stage117-tools-regression
```

Observed:

- `18 passed`

## Live DeepSeek Evidence

Live smoke used the configured `DEEPSEEK_API_KEY` without printing it.

Observed:

- `returncode=0`
- provider `deepseek`
- model `deepseek-v4-flash`
- `initial_finish_reason=tool_calls`
- final `finish_reason=stop`
- `agent_tool_loop.round_count=2`
- round 1 tool: `workspace_inspect`
- round 2 tool: `local_command`
- `executed_count=2`
- `skipped_count=0`
- `exhausted=false`

## Scope Boundary

No WeChat watcher or live transport process was started or modified.
