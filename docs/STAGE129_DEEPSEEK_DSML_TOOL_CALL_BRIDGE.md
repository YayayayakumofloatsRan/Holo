# Stage129 DeepSeek DSML Tool Call Bridge

Stage129 addresses a live CLI failure in the internal tool loop.

The Stage128 flow correctly forced `micro_fast -> subject_main` for memory,
factual correction, and tool-oriented turns, but a live DeepSeek response
returned tool calls as DSML markup inside `message.content`:

```text
<DSML tool_calls>
  <invoke name="workspace_inspect">...</invoke>
</DSML tool_calls>
```

Because the parser only handled OpenAI-style `message.tool_calls`, Holo printed
the markup to the user instead of executing the tool. That broke the intended
biomimetic loop:

1. first reaction
2. internal tool proposal
3. local WSL tool execution
4. tool observation compressed into the next provider packet
5. grounded external speech

## Runtime Contract

DeepSeek may return either of these equivalent tool surfaces:

- structured `choices[].message.tool_calls`
- DSML `tool_calls` markup embedded in `choices[].message.content`

Holo must normalize both into the same Stage113 local execution contract. The
provider never executes tools directly. It proposes calls; the WSL brain
validates and executes allowlisted tools, then sends bounded observations back
to the provider.

When DSML calls are normalized, Holo also strips the DSML markup from the
assistant message used in the follow-up packet, so the next provider call sees
clean prior speech plus a normal `tool_calls` array and matching `tool`
observations.

## Implementation Notes

- `stage106_deepseek_tool_adapter.parse_provider_tool_calls` now parses DSML
  `tool_calls` blocks from message content.
- DSML parameters with `string="true"` remain strings.
- DSML parameters with `string="false"` are JSON-decoded when possible, which
  preserves integers, booleans, arrays, and objects.
- `provider_tool_calls_for_message` converts normalized calls back to
  provider-style assistant `tool_calls` for the follow-up packet.
- `strip_provider_tool_markup` removes DSML markup from assistant content.
- `DeepSeekProvider._maybe_run_agent_tool_loop` uses the synthetic assistant
  `tool_calls` when the provider's first response only had DSML markup.

## Verification

Focused red/green tests:

```powershell
python -m pytest -q tests\test_stage106_deepseek_tool_adapter.py::test_stage106_parses_deepseek_dsml_tool_calls_from_content tests\test_stage115_deepseek_agent_tool_loop.py::test_deepseek_provider_executes_dsml_content_tool_call_and_requests_final_reply --basetemp=.pytest_tmp_stage129_dsml_green1
```

Result:

```text
2 passed in 0.14s
```

Related tool-chain regression:

```powershell
python -m pytest -q tests\test_stage106_deepseek_tool_adapter.py tests\test_stage115_deepseek_agent_tool_loop.py tests\test_stage116_multiround_agent_tools.py tests\test_stage117_complete_agent_tooling.py tests\test_stage118_tool_expansion.py tests\test_stage119_tool_library_expansion.py tests\test_stage123_internal_tool_flow.py tests\test_stage124_fast_deep_thought_loop.py tests\test_stage128_biomimetic_continuous_thought_flow.py --basetemp=.pytest_tmp_stage129_related2
```

Result:

```text
40 passed in 10.69s
```

Full repository verification:

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage129_final
```

Result:

```text
431 passed in 83.08s (0:01:23)
```

Live WSL probe after syncing to commit `fbf2863`:

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

The live CLI path also showed `micro_fast` followed by `subject_main` on the
same event, and no DSML markup leaked into user-visible speech.

DeepSeek-specific constraint: thinking mode rejects forced function
`tool_choice`, so the runtime should keep provider `tool_choice=auto` and let
the prompt plus tool schema induce the call.
