# Stage107 Provider Interaction Loop

Stage107 makes the bottom provider interaction mechanism explicit.

The practical model is:

```text
local state -> finite provider packet -> provider return -> compressed delta
-> next finite packet or local tool observation -> stop
```

This is the engineering surface for simulating a bounded consciousness stream.
The stream is not an infinite context window and not a single large prompt. It
is a finite packet loop with visible compression and stop conditions.

## Loop Phases

`provider_packet`

- A bounded packet from Stage105.
- Contains current query, compact recall, selected action, and any previous
  delta or tool observation.

`provider_return`

- The provider output for that packet.
- May contain text or accepted provider tool calls.

`distill_delta`

- A local compressed summary of the provider return.
- Carries only what is needed for the next packet.
- Has a stable digest so the loop can be visualized and audited.

`tool_request`

- A local tool request from Stage105 `tool_first`, or from provider-native
  `tool_calls` parsed by Stage106.
- Execution remains local to Holo, not the provider.

`tool_observation`

- The local result from a tool.
- The observation is compressed and inserted into the next provider packet.

`stop`

- A terminal event for `silence`, `defer`, or finished `reply_commit`.
- Prevents Holo from sending provider packets merely because a packet planner
  exists.

## Current CLI

```powershell
python -m holo_host stage107-interaction-loop --query "回忆任何事情？"
```

This dry-run command builds the loop up to the next executable phase. If no
provider return is present, it exposes only the next packet to send. It does not
pretend later packets have already occurred.

## Why This Matters

Stage105 decided how many finite packets are needed. Stage106 made provider
tool proposals safe. Stage107 now defines how packets, returns, compressed
deltas, and local observations advance.

This is where theory starts to affect behavior:

- working memory is the current packet;
- short-term thought is the provider return plus local delta compression;
- long-term continuity enters only through selected memory and attractors;
- tools reduce hallucination by inserting observations before the next packet;
- stopping is explicit instead of implicit.

## Not Yet Implemented

Stage107 is still a dry-run state machine. It does not call DeepSeek live and
does not execute tools. The next stage should attach the executor:

1. send the visible `provider_packet`;
2. parse the provider return;
3. execute accepted local tools when needed;
4. append tool observations;
5. continue until `reply_commit` or a stop condition.
