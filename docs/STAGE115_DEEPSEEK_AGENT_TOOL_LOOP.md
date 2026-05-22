# Stage115 DeepSeek Agent Tool Loop

## Purpose

Stage115 moves tool calling from a CLI or smoke-test surface into the real
DeepSeek provider path used by Holo chat. The target is provider-above agent
adaptation: the model may decide that it needs a local tool, but Holo validates
and executes the tool inside the local brain, then sends the compressed
observation back as the next bounded provider packet.

## Runtime Contract

Default Holo chat now attaches:
- `enable_provider_tools = true`
- `auto_execute_provider_tools = true`
- `tool_requests = [memory_recall, external_lookup, ...existing requests]`

The provider packet loop is:

1. Send user prompt with allowlisted DeepSeek tool schemas.
2. If DeepSeek returns `tool_calls`, parse and validate them through Stage106.
3. Execute accepted local tools through Stage113.
4. Send a second DeepSeek packet containing:
   - the original user message
   - the assistant message with original `tool_calls`
   - one `tool` role message per local observation
5. Commit only the final answer from the second packet.

Unknown tools, malformed arguments, and skipped calls remain local metadata; the
provider never receives direct execution authority.

## Available Tools

- `memory_recall`: local read-only memory recall, seeded with the current user
  text and thread identity.
- `external_lookup`: external evidence lookup, seeded with the current user
  text. If runtime network is disabled, execution is skipped locally and the
  skip reason is returned as a tool observation.

## Biomimetic Interpretation

This stage implements the smallest practical "act-perceive-reenter" loop:
language output is not treated as a single final utterance. A provider proposal
can become an internal action, the action is compressed into an observation,
and the final utterance is generated after that observation re-enters the
working context. That gives Holo a concrete substrate for tool-mediated
continuity rather than a single-shot answer.

## Verification

Primary regression:

```powershell
python -m pytest -q tests\test_stage115_deepseek_agent_tool_loop.py --basetemp .holo_runtime\pytest-stage115-green-chat
```

Expected result:
- provider tool-call packet triggers one local execution
- second provider packet includes assistant `tool_calls` and `tool`
  observation
- combined usage sums both provider packets
- ordinary chat metadata enables provider tools and automatic local execution
