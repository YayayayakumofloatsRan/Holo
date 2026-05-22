# Progress 2026-05-22 Stage116 Fluent Agent Tool Loop

## Result

Stage116 improves the DeepSeek tool path toward Codex-style fluent tool use.
The provider loop is now multi-round, budgeted, and observable.

Implemented:
- `DeepSeekProvider` can continue through multiple provider `tool_calls` rounds
  before committing the final answer.
- follow-up packets keep `tool_choice=auto` while there is remaining tool
  budget.
- rejected or unknown tool calls are returned to the provider as explicit
  `role=tool` observations.
- usage is accumulated across every provider packet in the loop.
- metadata records round count, per-round tool names, executed/skipped counts,
  call budget, and exhaustion state.

## Red-Green Evidence

Red:

```powershell
python -m pytest -q tests\test_stage116_multiround_agent_tools.py --basetemp .holo_runtime\pytest-stage116-red
```

Observed before implementation:
- multi-round test failed because Stage115 stopped after one tool-return cycle;
- rejected-tool test failed because unknown tools produced no follow-up tool
  observation.

Green:

```powershell
python -m pytest -q tests\test_stage116_multiround_agent_tools.py --basetemp .holo_runtime\pytest-stage116-green
```

Observed after implementation:
- `2 passed`

Compatibility regression:

```powershell
python -m pytest -q tests\test_stage115_deepseek_agent_tool_loop.py tests\test_stage116_multiround_agent_tools.py --basetemp .holo_runtime\pytest-stage116-stage115-green
```

Observed:
- `5 passed`

## Scope Boundary

No WeChat watcher or live transport process was started or modified. This stage
changes the provider loop, tests, and documentation only.
