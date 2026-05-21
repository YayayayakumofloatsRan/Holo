# Stage106 DeepSeek Tool Adapter Design

## Context

Holo can plan finite provider packets in Stage105. The next practical gap is
provider-native tool calling: DeepSeek can propose a function call, but Holo
must keep the single-subject execution boundary local.

## Design

Stage106 introduces a provider-agnostic adapter with three responsibilities:

1. Convert Holo `tool_requests` into OpenAI/DeepSeek-compatible `tools`.
2. Parse provider `message.tool_calls`.
3. Reject unknown tool names and invalid argument payloads before any execution.

`DeepSeekProvider` uses the adapter only when a request explicitly sets
`enable_provider_tools=true`. This avoids breaking normal speech turns with an
empty tool-call response before the executor loop exists.

## Tools

Initial allowlist:

- `external_lookup`: current external evidence request.
- `memory_recall`: read-only local Holo memory recall request.

Both require a `query` argument. Execution is not part of this stage.

## Data Flow

Stage105 emits a bounded tool affordance. Stage106 exposes the allowlisted
schema to the provider. The provider may return `tool_calls`. Holo validates the
calls and later executor work will turn accepted calls into observation packets
for the next Stage105 packet stream.

## Safety Boundary

The provider never executes tools. It proposes names and arguments only. Holo
keeps execution authority in WSL, rejects unknown tools, and rejects non-object
or malformed JSON arguments.

## Test Plan

- Tool schema generation from Stage105 `external_lookup`.
- Allowed DeepSeek/OpenAI-style `tool_calls` parsing.
- Unknown tool rejection.
- Invalid argument rejection.
- DeepSeek payload attachment only when explicitly enabled.
- CLI dry-run output.
