# Stage211 Persistent Action Ledger Recall

Stage211 extends Stage210 from current-process CLI memory to persisted reply metadata.

## Problem

Stage210 answered "what did you just search/do?" from `InteractiveCliSession.last_payload`. That fixed the same live CLI process, but a restarted CLI or direct `/reply` request had no `last_payload` and could fall back to provider guessing.

## Implementation

Schema:

```text
holo.stage211.persistent_action_recall.v1
```

Stage211 reads only recent same-thread `outbound` message metadata already stored in `QueueStore`. It looks for public action evidence such as:

- `stage186_live_crawler_search`
- `web_observation_ledger`
- `tool_observation_ledger`
- `stage153_agent_event_stream`

When the current user asks what Holo searched or did, Stage211 reconstructs a previous action payload from the newest persisted outbound ledger and reuses Stage210 to render the answer.

## Runtime Path

1. `/reply` records the inbound message.
2. It loads same-thread recent history.
3. Before memory sidecar or provider generation, Stage211 checks whether the user asks for the previous action.
4. If a persisted action ledger exists, Holo replies from the ledger and records a new outbound metadata row.
5. The result includes Stage153 event stream and Stage191 public thought cards.

## Public Thought Boundary

Stage211 does not expose raw hidden chain-of-thought or provider `reasoning_content`.

It exposes a public, auditable stream:

- previous action type
- query count
- promoted source count
- weak source count
- stop reason

This is enough to debug the agent's action loop without leaking private model internals.

## Constraints

- no provider call
- no memory write
- no tool execution
- no WeChat start
- no transport authority widening
- no weak-source promotion
