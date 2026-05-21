# Stage107 Provider Interaction Loop Design

## Context

Holo cannot train the base model, so the core research surface is provider-side
adaptation: deciding what finite packets to send, how to compress each return,
when to insert tool observations, and when to stop.

Stage105 plans packet roles. Stage106 adapts Holo tool requests to DeepSeek
tool-calling. Stage107 turns these pieces into an inspectable interaction loop.

## Design

The loop is a deterministic state machine. It does not call the provider during
dry-run. Instead, it describes the next executable phase and records enough
state for visualization and future live execution.

Phases:

- `provider_packet`: the next bounded packet to send.
- `provider_return`: the provider response for a packet.
- `distill_delta`: local compression of the provider response.
- `tool_request`: a local tool action required before continuing.
- `tool_observation`: the local result that enters the next packet.
- `stop`: a terminal no-send or completed reply-commit state.

## Stop Rules

- If Stage105 says `tool_request` and no observation is present, stop at
  `awaiting_tool_observation`.
- If a provider return contains accepted tool calls, stop at
  `awaiting_tool_execution`.
- If a provider packet has no return yet, expose that packet and stop at
  `ready_to_continue`.
- If Stage105 says `no_send`, preserve the stop condition and do not expose a
  provider packet.
- Only mark `complete` after all planned packets have provider returns and the
  final role is `reply_commit`.

## Safety

The provider never executes tools. Provider tool calls are converted into local
tool requests. Unknown or invalid tools are rejected earlier by Stage106.

## Tests

- Broad recall alternates provider packet, return, delta, next packet.
- Tool-first plans wait for local observation.
- Tool observations enter the next provider packet.
- Provider tool calls interrupt the stream for local execution.
- Delta compression has a stable budget and digest.
- CLI dry-run builds a Stage107 loop from the current mind packet.
