# Engineering Handoff Stage53

## Status

Stage53 implements Holo's upstream MCP tool substrate. The current priority is not exposing Holo to outside agents; it is giving the Holo subject kernel a controlled way to discover and call external MCP tools as observations.

Hard boundaries remain unchanged:

- WSL remains the authoritative subject kernel.
- Upstream MCP servers are tool/resource providers only.
- MCP results are observations, not decisions.
- No downstream Holo MCP server is enabled in this stage.
- No WeChat transport start, watcher authority, self-memory write, policy mutation, shell execution through MCP, or unbounded loop is added.

## Architecture Delta

- `holo_host/mcp_upstream.py`
  - Adds `McpStdioUpstreamClient` for JSON-RPC MCP stdio initialization, tool listing, tool calls, and resource reads.
  - Adds `McpUpstreamServerConfig`, `McpUpstreamRegistry`, and `McpUpstreamHub`.
  - Reads `[mcp_servers.<name>]` blocks from `.holo_host.toml`.
  - Requires argv-style stdio commands and rejects shell command strings.
  - Namespaces tools as `server.tool` and filters discovery/calls through `allowed_tools`.
  - Wraps tool/resource returns in a Stage53 boundary envelope where upstream results are observations only.
- `holo_host/engineering_agent.py`
  - Adds `mcp_list_tools`, `mcp_call_tool`, and `mcp_read_resource` as `external_observation` tools.
  - Keeps these tools behind action-market gating and server/tool allowlists.
  - Marks failed MCP observations as verification failures.
  - Tracks `mcp_tool_count` in engineering-agent metrics.
- `holo_host/cli.py`
  - Adds `show-mcp-upstream-status`.
  - Adds `list-mcp-upstream-tools`.
  - Adds `call-mcp-tool --tool server.tool --arguments-json '{...}'`.
  - Adds `read-mcp-resource --server name --uri uri`.
- `.holo_host.example.toml`
  - Documents disabled example upstream servers and the required allowlist pattern.

## Operator Flow

1. Configure an upstream server in `.holo_host.toml`:

```toml
[mcp_servers.toolbox]
enabled = true
command = ["python", "path/to/server.py"]
allowed_tools = ["echo", "search"]
timeout_seconds = 30
max_response_bytes = 1000000
```

2. Inspect static registry state:

```powershell
python -m holo_host show-mcp-upstream-status
```

3. Discover allowlisted tools:

```powershell
python -m holo_host list-mcp-upstream-tools
```

4. Call a tool manually as an observation:

```powershell
python -m holo_host call-mcp-tool --tool toolbox.echo --arguments-json '{"value":"hello"}'
```

Inside the Stage41 engineering agent, the model can request:

```json
{"tool":"mcp_call_tool","mutation_class":"external_observation","qualified_name":"toolbox.echo","arguments":{"value":"hello"}}
```

That action still passes through the action market and the same allowlist before any process is launched.

## Protocol Notes

The implementation follows the MCP JSON-RPC lifecycle shape: initialize first, then `notifications/initialized`, then server feature methods such as `tools/list`, `tools/call`, and `resources/read`.

Reference surfaces:

- https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
- https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- https://modelcontextprotocol.io/specification/2025-11-25/server/resources

## Verification

- `python -m pytest -q tests\test_stage53_mcp_upstream.py`: `9 passed`
- `python -m pytest -q tests\test_stage41_engineering_agent.py tests\test_stage53_mcp_upstream.py`: `15 passed`
- `python -m py_compile holo_host\mcp_upstream.py holo_host\engineering_agent.py holo_host\cli.py`: passed
- `python -m holo_host show-mcp-upstream-status`: returned an empty configured-server registry with Stage53 boundary fields.
- `python -m holo_host --help`: includes `show-mcp-upstream-status`, `list-mcp-upstream-tools`, `call-mcp-tool`, and `read-mcp-resource`.
- `git diff --check`: no whitespace errors; Git emitted only CRLF conversion warnings for existing text files.
- `python -m pytest -q`: `410 passed`
- `python scripts\check_public_release_hygiene.py`: passed

## Next Direction

The next useful expansion is breadth through configuration, not new authority:

- add reviewed MCP server configs for filesystem, git, browser/search, and document tooling
- keep each server disabled until its command, cwd, timeout, output budget, and `allowed_tools` are reviewed
- route tool choice through the existing subject/engineering action market
- add per-server latency and failure metrics before relying on any server in long agent loops
