# Progress 2026-05-22: Stage114 Live DeepSeek Tool Test

## Goal

Verify Stage114 against DeepSeek's official tool-calling API surface, not only a
simulated provider response.

## Official Contract Checked

DeepSeek official docs state:

- `/chat/completions` accepts `tools`.
- `tool_choice` can be `none`, `auto`, `required`, or a named function choice.
- `finish_reason=tool_calls` means the model called a tool.
- Returned `message.tool_calls[].function.arguments` are JSON strings and must
  be validated by local code.
- Function implementation is provided by the user side; the model itself does
  not execute the function.

Docs used:

- https://api-docs.deepseek.com/api/create-chat-completion
- https://api-docs.deepseek.com/guides/function_calling
- https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code

## Live Smoke Test

Used existing `DEEPSEEK_API_KEY` from the environment. The key was not printed.

Request shape:

- endpoint: `https://api.deepseek.com/chat/completions`
- model: `deepseek-v4-flash`
- `thinking.type=disabled`
- one allowlisted function: `memory_recall`
- `tool_choice={"type":"function","function":{"name":"memory_recall"}}`

The decoded DeepSeek response was passed directly into
`run_stage114_agent_tool_cycle(...)`.

## Observed Result

```json
{
  "api_model": "deepseek-v4-flash",
  "finish_reason": "tool_calls",
  "raw_tool_call_count": 1,
  "accepted_names": ["memory_recall"],
  "rejected_errors": [],
  "executed_count": 1,
  "observation_tools": [["memory_recall", "ok"]],
  "next_provider_packet_available": true,
  "has_tool_observation_summary": true,
  "can_continue_agent_loop": true,
  "usage": {
    "prompt_tokens": 360,
    "completion_tokens": 55,
    "total_tokens": 415
  }
}
```

## Conclusion

Stage114 passed a live DeepSeek tool-call smoke test:

```text
DeepSeek real tool_call -> Stage106 parse -> Stage113 local execution
-> Stage107 observation reentry -> next provider packet ready
```

This verifies the minimum useful agent tool loop. The remaining production work
is to wire this cycle into the main Holo chat/reply runtime so normal dialogue
can invoke it automatically.
