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

## Live WSL Smoke

After syncing WSL to commit `fbf2863`, a CLI read-only directory request
returned a normal user-visible answer and did not leak DSML markup. The usage
ledger showed the intended two-speed flow on event `82`:

```text
micro_fast: id=1228, status=ok, total_tokens=299
subject_main: id=1231, status=ok, total_tokens=10043
```

A direct live provider probe reused the running WSL brain environment without
printing the API key and exercised the internal tool loop:

```text
returncode=0
initial_finish_reason=tool_calls
finish_reason=stop
tool_call_count=1
agent_round_count=1
agent_executed_count=1
agent_skipped_count=0
tool_names=["workspace_inspect"]
observation_summary="workspace list_dir: .agent, .codex, .git, .github, .holo_runtime, .vendor, artifacts, deploy"
```

Provider constraint observed during the smoke: DeepSeek thinking mode rejects a
forced function `tool_choice` with `Thinking mode does not support this
tool_choice`. The operational path should keep `tool_choice=auto` and let the
prompt/tool schema induce tool use.

## Remaining Work

The live tool loop is now confirmed. The next reliability improvement is to add
first-class CLI/debug surfacing for `agent_tool_loop` metadata, so this evidence
does not require a direct provider probe.
