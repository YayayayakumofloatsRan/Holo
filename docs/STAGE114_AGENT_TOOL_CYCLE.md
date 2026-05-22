# Stage114 Agent Tool Cycle

Stage114 connects provider tool proposals to local execution and packet
continuation.

Stage113 can execute tools. Stage114 makes it an agent loop:

```text
provider_return.tool_calls
-> Stage106 parser
-> Stage113 local execution
-> Stage107 tool_observation event
-> next provider_packet inputs
```

It also supports Stage105 `tool_first` plans, where the local tool is executed
before any provider packet is sent.

## What It Proves

- Provider tool calls can be parsed.
- Allowlisted tools execute locally.
- Rejected tools stay skipped.
- Tool observations re-enter Stage107.
- The next provider packet receives `tool_observation_summary`.

This is the minimum closed loop needed for useful agent tool behavior.

## CLI

Simulate provider asking for memory recall:

```powershell
python -m holo_host stage114-agent-tool-cycle --query "provider packet continuity" --simulate-tool memory_recall
```

Simulate provider asking for external lookup and memory recall:

```powershell
python -m holo_host stage114-agent-tool-cycle --query "provider packet continuity" --simulate-tool both --live-network
```

The command does not require a live provider call. It simulates the provider
`tool_calls` surface, then executes the tools locally. A later live stage can
replace the simulated provider response with an actual DeepSeek response.

## Output Contract

- `provider_tool_calls`: parsed provider proposals.
- `tool_execution`: Stage113 execution report.
- `reentry_loop`: Stage107 loop after observations are attached.
- `next_provider_packet`: packet inputs ready for the next provider call.
- `ready.can_continue_agent_loop`: true when the loop can continue.
