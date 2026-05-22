# Stage117 Complete Agent Tooling

## Purpose

Stage117 closes the main gap left after Stage116. The loop could continue
through multiple tool rounds, but the actual tool surface was too narrow:
`memory_recall` and `external_lookup` were not enough for Codex-level agent
work. Holo now exposes bounded workspace inspection and allowlisted local
verification commands through the same DeepSeek tool-call loop.

## Tool Surface

Default ordinary Holo chat now exposes:

- `memory_recall`: local semantic memory recall.
- `external_lookup`: external evidence lookup when network is enabled.
- `workspace_inspect`: bounded local workspace list/read/search.
- `local_command`: strictly allowlisted argv-based verification commands.

`local_command` does not accept shell strings. Initial allowlist:

- `git status --short`
- `git diff --check`
- `git diff --stat`
- `git log -1 --oneline`
- `python -m pytest ...`
- `python3 -m pytest ...`
- `py -m pytest ...`

This gives the provider real hands for inspection and verification without
handing it unrestricted process execution.

## Provider Contract

The DeepSeek adapter now preserves named `tool_choice` objects. This matters
for live smokes where we force the first tool call, then let follow-up packets
return to `tool_choice=auto`.

Example first packet:

```json
{"type": "function", "function": {"name": "workspace_inspect"}}
```

Follow-up packets use `auto` while budget remains, so the model can decide
whether to call `local_command`, another inspection, or stop with a final
answer.

## Verification

Primary regression:

```powershell
python -m pytest -q tests\test_stage117_complete_agent_tooling.py --basetemp .holo_runtime\pytest-stage117-green1
```

Expected result:

- named `tool_choice` is preserved;
- workspace read returns a tool observation;
- allowlisted local command returns a tool observation;
- provider completes `workspace_inspect -> local_command -> final`;
- ordinary chat metadata includes all four default tools.

Live DeepSeek smoke:

- forced first tool: `workspace_inspect`
- automatic second tool: `local_command`
- final answer returned with `finish_reason=stop`
- observed `agent_tool_loop.round_count=2`
- observed `executed_count=2`
- observed `exhausted=false`
