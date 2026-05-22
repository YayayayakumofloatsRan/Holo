# Progress 2026-05-22 Stage115 DeepSeek Agent Tool Loop

## Result

Stage115 integrates provider-native tool calling into the live DeepSeek provider
path and the ordinary Holo chat entrypoint.

Implemented:
- `DeepSeekProvider` now handles `tool_calls` by executing accepted local tools
  through Stage113 and sending a second `chat/completions` request with tool
  observations.
- usage accounting now combines the initial proposal packet and the final reply
  packet.
- normal `CodexCliProcessor.generate()` chat calls default to exposing
  `memory_recall` and `external_lookup` provider tools with
  `auto_execute_provider_tools=true`.
- provider compatibility contract now records Stage115 as a required live-agent
  behavior.

## Red-Green Evidence

Red:

```powershell
python -m pytest -q tests\test_stage115_deepseek_agent_tool_loop.py --basetemp .holo_runtime\pytest-stage115-red
```

Observed before implementation:
- first test failed because DeepSeek returned `tool_calls`, but provider text
  stayed empty and no second provider packet was sent.

Green:

```powershell
python -m pytest -q tests\test_stage115_deepseek_agent_tool_loop.py --basetemp .holo_runtime\pytest-stage115-green-chat
```

Observed after implementation:
- `3 passed`

## Scope Boundary

No WeChat watcher or live transport process was started or modified. This stage
changes the provider loop and chat metadata only.
