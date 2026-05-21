# Stage105 Provider Packet Stream

Stage105 makes Holo's provider-layer theory executable. The base model is not trained here; Holo controls the situation that reaches the provider.

## Principle

The provider is a strong stateless inference engine. Holo's local work is to decide:

- what compact packet to send;
- how many bounded packets to send;
- how to distill the previous output into the next packet;
- when not to send;
- when a timely single packet matters more than deeper deliberation;
- when a tool call should happen before more provider inference.

This is the engineering version of a limited consciousness stream: packet, provider output, distilled delta, next packet.

## Packet Roles

`context_seed`

- First packet.
- Carries query, Stage104 semantic attractors, selected action, recall lines, and current uncertainty.
- Its job is to put the provider in the right situation.

`deliberation_delta`

- Second packet when uncertainty or broad recall warrants more thought.
- It should contain the compressed output of the previous provider call, not raw transcript sprawl.
- It asks for semantic delta, unresolved uncertainty, and tool affordance.

`reply_commit`

- Final packet.
- It commits to the reply plan or a stop condition.
- It must not continue deliberation unless a tool is required.

## Send Policy

`send_multi`

- Used for broad recall, high uncertainty, or multiple semantic attractors.
- Example: `回忆任何事情？` planned 3 packets:
  - `context_seed`
  - `deliberation_delta`
  - `reply_commit`

`send_once`

- Used when context is already sufficient and uncertainty is low.
- The system still gives the provider one finite packet, then stops.

`send_punctual`

- Used when deadline pressure is high and the selected action still permits sending.
- It sends a single punctual packet rather than spending budget on deeper deliberation.

`do_not_send`

- Used when the action layer selected silence or defer.
- This keeps Holo from compulsively sending just because a packet can be constructed.

`tool_first`

- Used when the query itself asks for lookup/current state, or the selected action is `external_lookup`.
- Stage105 emits a `tool_request` before further provider packets.
- Example: `查一下最新状态` now plans `next_action=tool_request`.

## Tool Boundary

Stage105 does not execute tools by itself. It emits an affordance:

```json
{
  "name": "external_lookup",
  "reason": "...",
  "payload": {
    "query": "...",
    "source": "stage105.provider_packet_stream"
  }
}
```

The tool result should come back as an observation packet and then enter the same distill-and-repack loop.

## Visualization Contract

Every Stage105 plan contains:

- packet nodes;
- `distill_and_repack` edges;
- packet roles;
- token budget per packet;
- timing mode;
- stop reason;
- next action;
- tool requests.

That means the visualization can stop drawing abstract complexity and instead show the actual finite-context stream Holo intends to run.

## Current Evidence

Local command:

```powershell
python -m holo_host stage105-packet-stream --query "回忆任何事情？" --max-packets 4
```

Observed:

- `packet_count=3`
- `send_decision=send_multi`
- `stop_reason=bounded_stream_ready`
- packets: `context_seed -> deliberation_delta -> reply_commit`

Local command:

```powershell
python -m holo_host stage105-packet-stream --query "查一下最新状态" --max-packets 4
```

Observed:

- `packet_count=1`
- `next_action=tool_request`
- `stop_reason=tool_first`
- tool: `external_lookup`

This is the practical bridge from theory to provider behavior: Holo can now explain why it sends multiple packets, why it stops, and why it should use a tool before asking the provider to guess.
