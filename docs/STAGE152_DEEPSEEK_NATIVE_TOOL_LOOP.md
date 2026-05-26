# Stage152 DeepSeek Native Tool Loop

Date: 2026-05-27

## Purpose

Stage152 connects DeepSeek thinking-mode `tool_calls` to Holo's host tool loop. The provider may request tools, but Holo still executes them locally, records normalized observations, and feeds `role=tool` results back into the next DeepSeek packet.

This stage targets the failure seen in CLI tests where Holo claimed web lookup without a matching observation. The new loop makes the packet chain auditable:

```text
purpose -> candidate -> tool -> observation -> evaluate -> stop -> final
```

## Schemas

```text
holo.stage152.deepseek_tool_loop.v1
holo.stage152.live_trace.v1
holo.web_observation.v1
holo.time_observation.v1
```

## Native Tool Registry

DeepSeek receives native function schemas for:

- `time_observe`
- `web_search`
- `open_page`
- `find_in_page`
- `memory_recall`

These are separate from the older Stage106/113 engineering tool registry. Stage106 remains available for existing regression paths; Stage152 is enabled for the live DeepSeek reply path.

## Thinking-Mode Continuity

When DeepSeek returns `tool_calls`, Holo appends an assistant message containing:

- visible assistant `content`
- internal `reasoning_content`, when present
- original `tool_calls`

Holo then executes the host tools and appends one `role=tool` message per result. The loop continues until DeepSeek returns no tool calls or the host stop controller reaches the configured round/call budget.

`reasoning_content` is retained only inside the provider continuity packet. It is not printed in CLI trace and is not exposed in public reply metadata.

## Observation Ledgers

Every native tool call produces host-side evidence:

- web tools produce `web_observation_ledger` rows and compatible `tool_observation_ledger` rows.
- `time_observe` produces a `time_observation` row and compatible tool observation.
- `memory_recall` produces read-only memory observation metadata and compatible tool observation.

Network access still respects `runtime.network_enabled`. If disabled, web tools return `rejected_network_disabled` and no fetch is attempted.

## Grounding

Stage152 reuses Stage151 web/time grounding. Final current or web claims require successful web/time observations. Without a ledger, the answer is repaired into bounded language before it leaves the loop.

## CLI Trace

`python3 -m holo_host chat --trace --no-local-fallback`

When Stage152 metadata is present, CLI trace prefers Stage152:

```text
[purpose] native_deepseek_tool_loop
[candidate] web_search score=0.5 need=web_search
[tool] web_search id=call_web status=accepted query=OpenAI Codex CLI docs
[observation] web_search status=ok results=1 sources=https://developers.openai.com/codex/cli
[evaluate] status=grounded missing=-
[stop] model_final_no_tool_calls
[final] ...
```

No hidden chain-of-thought or raw `reasoning_content` appears in this trace.

## Boundaries

Stage152 does not start WeChat, widen transport authority, add approval/sandbox logic, write memory, or execute tools outside the existing WSL host authority. It adds provider-native tool-loop continuity and observability only.

