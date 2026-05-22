# Progress 2026-05-22 Stage129 DeepSeek DSML Tool Call Bridge

## Trigger

Live CLI testing after Stage128 showed that DeepSeek could return tool calls as
DSML markup embedded in `message.content`. Holo printed that markup instead of
executing the local tool loop.

## Changes

- Added DSML content parsing to Stage106 provider tool-call normalization.
- Added conversion from normalized DSML calls back to provider-style assistant
  `tool_calls` for the follow-up packet.
- Stripped DSML markup from assistant content before sending tool observations
  back to the provider.
- Added regression tests for DSML parsing and DSML-driven automatic local tool
  execution.

## Verification

```powershell
python -m pytest -q tests\test_stage106_deepseek_tool_adapter.py::test_stage106_parses_deepseek_dsml_tool_calls_from_content tests\test_stage115_deepseek_agent_tool_loop.py::test_deepseek_provider_executes_dsml_content_tool_call_and_requests_final_reply --basetemp=.pytest_tmp_stage129_dsml_red
```

Expected red result:

```text
2 failed
```

```powershell
python -m pytest -q tests\test_stage106_deepseek_tool_adapter.py::test_stage106_parses_deepseek_dsml_tool_calls_from_content tests\test_stage115_deepseek_agent_tool_loop.py::test_deepseek_provider_executes_dsml_content_tool_call_and_requests_final_reply --basetemp=.pytest_tmp_stage129_dsml_green1
```

Green result:

```text
2 passed in 0.14s
```

```powershell
python -m pytest -q tests\test_stage106_deepseek_tool_adapter.py tests\test_stage115_deepseek_agent_tool_loop.py tests\test_stage116_multiround_agent_tools.py tests\test_stage117_complete_agent_tooling.py tests\test_stage118_tool_expansion.py tests\test_stage119_tool_library_expansion.py tests\test_stage123_internal_tool_flow.py tests\test_stage124_fast_deep_thought_loop.py tests\test_stage128_biomimetic_continuous_thought_flow.py --basetemp=.pytest_tmp_stage129_related2
```

Green result:

```text
40 passed in 10.69s
```

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage129_final
```

Full repository result:

```text
431 passed in 83.08s (0:01:23)
```

## Remaining Work

Run a live WSL CLI smoke after syncing this patch to the WSL brain. The desired
evidence is an `agent_tool_loop.executed_count > 0` on a tool-seeking turn, with
no DSML markup leaked into user-visible speech.
