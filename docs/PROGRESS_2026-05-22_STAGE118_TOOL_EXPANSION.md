# Progress 2026-05-22 Stage118 Tool Expansion

## Result

Stage118 expands the provider-callable local tool surface from four tools to
eight tools.

Added:

- `workspace_edit`
- `git_inspect`
- `test_runner`
- `progress_note`

Now exposed by default in ordinary Holo chat:

- `memory_recall`
- `external_lookup`
- `workspace_inspect`
- `local_command`
- `workspace_edit`
- `git_inspect`
- `test_runner`
- `progress_note`

## Red-Green Evidence

Red:

```powershell
python -m pytest -q tests\test_stage118_tool_expansion.py --basetemp .holo_runtime\pytest-stage118-red
```

Observed before implementation:

- provider payload exposed only four tools;
- `workspace_edit`, `git_inspect`, `test_runner`, and `progress_note` all
  executed zero tools;
- provider-chain simulation could not create the requested workspace file;
- ordinary chat metadata exposed only memory, lookup, workspace inspection, and
  local command tools.

Green:

```powershell
python -m pytest -q tests\test_stage118_tool_expansion.py --basetemp .holo_runtime\pytest-stage118-green2
```

Observed:

- `5 passed`

Tool regression:

```powershell
python -m pytest -q tests\test_stage106_deepseek_tool_adapter.py tests\test_stage113_agent_tool_executor.py tests\test_stage115_deepseek_agent_tool_loop.py tests\test_stage116_multiround_agent_tools.py tests\test_stage117_complete_agent_tooling.py tests\test_stage118_tool_expansion.py --basetemp .holo_runtime\pytest-stage118-tools-regression
```

Observed:

- `23 passed`

## Live DeepSeek Evidence

Live smoke used a temporary repo root and the configured `DEEPSEEK_API_KEY`
without printing it.

Observed:

- forced `workspace_edit` tool call;
- wrote `notes/live_stage118.txt`;
- final `finish_reason=stop`;
- `agent_tool_loop.round_count=1`;
- `executed_count=1`;
- `skipped_count=0`;
- `exhausted=false`;
- written text was `live stage118 tool ok`.

## Scope Boundary

No WeChat watcher or live transport process was started or modified.
