# Stage120 Agent Architecture Audit and Tool Selection

Date: 2026-05-22

## Architecture Check

Current Holo agent flow:

1. `HoloReplyService.handle_reply` receives a turn and builds memory, sidecar,
   and capability context.
2. `CapabilityBroker.summarize_turn` contributes external lookup, attachment,
   and permission metadata.
3. `CodexCliProcessor.generate` renders the bounded chat prompt, selects the
   provider lane, and builds provider tool requests.
4. `DeepSeekProvider.run_task` sends the provider packet with OpenAI-compatible
   tool schemas.
5. `DeepSeekProvider._maybe_run_agent_tool_loop` parses provider tool calls,
   executes them locally through Stage113, appends observations, and sends the
   next bounded provider packet.
6. `execute_stage113_agent_tools` remains the local authority boundary:
   providers propose, Holo executes.

The most important architecture issue after Stage119 was not tool execution
coverage. It was tool visibility. Stage119 correctly created a 41-tool library,
but `_agent_tool_requests` exposed all 41 schemas by default. The full schema
payload is about 18,948 JSON characters, roughly 4,700 tokens before normal
prompt text. That makes every turn more expensive and gives the provider a
wider, noisier action set than the actual working memory state requires.

## Single-Point Optimization

Stage120 separates:

- **tool library**: all registered tools Holo can execute;
- **tool working set**: the smaller set visible to the provider for this turn.

The optimizer ranks tools from four signals:

- explicit tool requests from capability context;
- baseline tools needed for continuous agent behavior;
- query/topic hints such as memory, workspace, docs, git, tests, runtime,
  artifacts, time, and modification intent;
- explicit host permission grants for modifying tools.

Default selected tools are bounded to 18. A diagnostic full scope remains
available through `tool_scope=full` or:

```text
python -m holo_host stage120-tool-affordance --query "run pytest and git diff" --full
```

Bounded inspection:

```text
python -m holo_host stage120-tool-affordance --query "run pytest and git diff"
```

## Authority Boundaries

- Stage120 does not start or touch WeChat/watchers.
- The WSL/local brain remains the only executor.
- Permissioned tools remain hidden unless explicitly requested/granted or
  preserved as explicit tool requests.
- Tool selection changes provider visibility only; it does not weaken Stage113
  path checks, command allowlists, or host permission gates.

## Verification

- `python -m pytest -q tests/test_stage120_tool_affordance_optimizer.py --basetemp=.pytest_tmp_stage120`
- `python -m pytest -q tests/test_stage118_tool_expansion.py tests/test_stage119_tool_library_expansion.py tests/test_stage120_tool_affordance_optimizer.py --basetemp=.pytest_tmp_tool_selection`

