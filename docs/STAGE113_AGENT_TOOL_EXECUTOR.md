# Stage113 Agent Tool Executor

Stage113 turns provider tool proposals into local tool execution.

The boundary remains:

```text
provider proposes tool_calls
-> Holo validates allowlist and arguments
-> Holo executes locally
-> tool_observation re-enters Stage107
-> next provider packet receives compressed observation
```

The provider still cannot execute tools. That is the point of the boundary:
execution belongs to the local agent brain, not the model provider.

## Supported Tools

`external_lookup`

- Purpose: current external evidence.
- Execution: local lookup executor with DuckDuckGo HTML and Bing HTML fallback.
- Network: disabled by default in CLI; enabled explicitly with
  `--live-network`.
- Observation: titles, URLs, snippets, status, and error if any.

`memory_recall`

- Purpose: read-only local memory recall.
- Execution: local corpus ranking by query-term overlap.
- Observation: matched memory ids, scores, matched terms, excerpts.

## Unknown Tools

Unknown or rejected provider tool calls are not executed. They are returned in
`skipped` with the rejection reason.

## CLI

Memory recall:

```powershell
python -m holo_host stage113-agent-tools --tool memory_recall --query "provider packet continuity"
```

External lookup with live network:

```powershell
python -m holo_host stage113-agent-tools --tool external_lookup --query "DeepSeek API status" --live-network
```

Both tools:

```powershell
python -m holo_host stage113-agent-tools --tool both --query "provider packet continuity" --live-network
```

## Reentry

Stage113 output includes:

- `observations`: the tool observations to pass into Stage107.
- `summary.observation_summary`: compact evidence summary.
- `reentry_contract.stage107_tool_observations`: exact payload for Stage107.

Stage107 already accepts `tool_observations` and inserts a
`tool_observation` event before the next `provider_packet`.
