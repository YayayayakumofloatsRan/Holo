# Progress: Stage120 Agent Architecture Audit and Tool Selection

Date: 2026-05-22

## Goal

Inspect the agent architecture after Stage119 and optimize one high-leverage
algorithmic point.

## Finding

The architecture is now functionally capable of provider tool calls, local tool
execution, permissioned modification, and observation reentry. The immediate
algorithmic inefficiency was the Stage119 default affordance surface:

- library size: 41 tools;
- full tool schema payload: about 18,948 JSON characters;
- rough token estimate: about 4,700 tokens before normal prompt text;
- effect: every turn made the provider choose among a large irrelevant action
  set.

## Completed

- Added `holo_host/stage120_tool_affordance_optimizer.py`.
- Changed ordinary provider tool exposure from full-library default to a
  bounded topic-sensitive working set.
- Preserved explicit tool requests and permission-granted tools.
- Preserved full library diagnostics with `tool_scope=full`.
- Added CLI inspection:

```text
python -m holo_host stage120-tool-affordance --query "run pytest and git diff"
```

This bounded probe selected 13 tools from the 41-tool library for the
`git + tests` query.

- Updated Stage118/Stage119 tests for the new separation between tool library
  and per-turn tool working set.
- Did not touch live WeChat or watcher transport.

## Verification

```text
python -m pytest -q tests/test_stage120_tool_affordance_optimizer.py --basetemp=.pytest_tmp_stage120
5 passed in 0.67s
```

```text
python -m pytest -q tests/test_stage118_tool_expansion.py tests/test_stage119_tool_library_expansion.py tests/test_stage120_tool_affordance_optimizer.py --basetemp=.pytest_tmp_tool_selection
14 passed in 8.22s
```

```text
python -m pytest -q tests/test_stage106_deepseek_tool_adapter.py tests/test_stage113_agent_tool_executor.py tests/test_stage117_complete_agent_tooling.py tests/test_stage118_tool_expansion.py tests/test_stage119_tool_library_expansion.py tests/test_stage120_tool_affordance_optimizer.py --basetemp=.pytest_tmp_stage120_regression
28 passed in 8.65s
```

```text
python -m pytest -q --basetemp=.pytest_tmp_full_stage120
402 passed in 71.80s (0:01:11)
```

## Next

The next useful optimization is empirical: run categorized simulated dialogues
and compare tool-choice precision, provider token usage, and hallucination
reduction before and after Stage120 selection.
