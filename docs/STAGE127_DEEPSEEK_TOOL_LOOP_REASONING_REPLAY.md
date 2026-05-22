# Stage127 DeepSeek Tool Loop Reasoning Replay

Stage127 fixes the live CLI tool-call failure that surfaced as:

```text
[ignore: processor_failure]
```

The visible CLI failure was misleading. The primary DeepSeek request reached the
provider and entered the agent tool loop, but the follow-up packet was rejected
before the model could produce the final answer.

## Root Cause

DeepSeek thinking-mode tool calls return an assistant message that can include
`reasoning_content`. When Holo sends the next packet with tool observations, the
assistant tool-call message must be replayed with that `reasoning_content`.

Holo previously replayed only:

```json
{"role": "assistant", "content": "", "tool_calls": [...]}
```

DeepSeek rejected that second packet with:

```text
The `reasoning_content` in the thinking mode must be passed back to the API.
```

The failure was then masked by provider fallback. The backup
`openai_compatible` lane was unavailable because the OpenAI SDK is not installed
in the live WSL environment, so the user-facing error collapsed to
`openai package not installed` instead of showing the primary DeepSeek protocol
error.

## Runtime Contract

Provider tool loops now preserve packet continuity:

1. user packet asks DeepSeek for a reply or tool decision
2. DeepSeek may return tool calls plus `reasoning_content`
3. Holo executes approved tools locally
4. Holo sends the assistant tool-call message back with the same
   `reasoning_content`
5. Holo appends tool observation messages
6. DeepSeek produces the final user-facing answer

Provider routing failures also keep the full chain of errors. A primary
provider protocol failure and a backup provider availability failure are both
visible in `ProcessorTaskResult.stderr`.

## Verification

Focused regression:

```powershell
python -m pytest -q tests\test_processor_fabric.py::CodexRunnerRoutingTests::test_failed_provider_result_keeps_primary_and_fallback_errors tests\test_stage115_deepseek_agent_tool_loop.py::test_deepseek_provider_executes_tool_call_and_requests_final_reply --basetemp=.pytest_tmp_stage127_green
```

Result:

```text
2 passed in 0.12s
```

Related agent/tool/thought-loop suite:

```powershell
python -m pytest -q tests\test_processor_fabric.py tests\test_stage115_deepseek_agent_tool_loop.py tests\test_stage116_multiround_agent_tools.py tests\test_stage117_complete_agent_tooling.py tests\test_stage118_tool_expansion.py tests\test_stage119_tool_library_expansion.py tests\test_stage123_internal_tool_flow.py tests\test_stage124_fast_deep_thought_loop.py --basetemp=.pytest_tmp_stage127_related
```

Result:

```text
36 passed in 11.76s
```

Full repository verification:

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage127_cli_tools
```

Result:

```text
425 passed in 85.66s (0:01:25)
```

Live WSL verification after deployment:

```powershell
wsl.exe -d HoloUbuntu --cd /home/holo/holo -- git rev-parse --short HEAD
wsl.exe -d HoloUbuntu --cd /home/holo/holo -- python3 -m holo_host show-provider-status
wsl.exe -d HoloUbuntu --cd /home/holo/holo -- python3 -m holo_host chat --thread-key holo_cli:main --chat-name HoloCLI --channel holo_cli --once "read your own repository directory in read-only mode" --json
wsl.exe -d HoloUbuntu --cd /home/holo/holo -- python3 -m holo_host show-usage-ledger --task-type reply --limit 8
```

Observed result:

```text
WSL head: 1a08c0b
provider: deepseek available=true
openai_compatible: available=false reason="openai package not installed"
CLI reply: no [ignore: processor_failure]; reply listed repository root entries
usage ledger: latest micro_fast and subject_main reply packets both status=ok provider=deepseek
latest subject_main duration_ms=13340 total_tokens=11106
transport: stopped; WeChat transport was not started
```
