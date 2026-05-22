# Stage122 Internal/External Channel Boundary

Stage122 adds an explicit channel boundary for the continuous thought stream.
The goal is not to expose hidden reasoning. The goal is to let Holo's local
runtime know which state is internal, which state is local processing metadata,
and which text is allowed to become external speech.

## First Principles

Provider-above agency is bounded by packet construction. Holo cannot assume an
infinite context window, and it cannot train the base model. The useful control
surface is therefore:

1. decide what the current packet is trying to do
2. summarize local processing without leaking raw hidden reasoning
3. commit only a user-visible expression to the outside channel

This mirrors the working-memory / expression boundary:

- `external_user`: what came from the outside world
- `internal_intent`: what the local subject controller is trying to do next
- `internal_processing`: local summary of phases, tools, uncertainty, and
  packet continuity
- `external_speech`: the only content that can become the visible reply

## Runtime Contract

`holo_host/stage122_internal_external_channel_boundary.py` creates a
`stage122_channel_frame` with three operative channels:

- `internal_intent`
  - local planning metadata
  - invisible to the user
  - modes include `compose_external_reply`, `tool_grounded_deliberation`,
    `ground_state_before_speaking`, and `continue_internal_deliberation`
- `internal_processing`
  - summary-only runtime state
  - includes Stage121 stream phases, tool names, uncertainty, and cache digest
  - explicitly disallows raw hidden reasoning traces
- `external_speech`
  - user-visible expression channel
  - `external_speech_only=true`
  - cannot include internal processing traces

`CodexCliProcessor.generate()` now:

1. appends a stable `Stage122 Channel Boundary` contract to the prompt
2. builds Stage121 packet policy against the actual prompt sent to provider
3. builds `stage122_channel_frame`
4. attaches that frame to provider metadata and reply debug output

The provider sees a stable expression contract. Holo keeps the detailed channel
frame locally in metadata. This preserves cacheability while making the local
subject boundary inspectable.

## Relationship To Stage121

Stage121 decides how long and how deep the provider packet should be. Stage122
decides what each channel means inside that packet flow.

- Stage121 answers: how much context, how many tool rounds, when to send again
- Stage122 answers: what is internal intent, what is local processing, what is
  external speech

When Stage121 chooses `continuous_thought`, Stage122 normally sets
`internal_intent.mode=continue_internal_deliberation`. That gives Holo a local
state for "still thinking / still integrating observations" without requiring
the provider to print hidden chain-of-thought.

## Operator Surface

Inspect the current channel-boundary frame:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host stage122-channel-boundary --query '连续思考流要区分内部意向和外部表达' --uncertainty 0.8 --tool memory_recall --tool tool_registry"
```

The command is read-only and does not spend provider tokens.

## Verification

```powershell
python -m pytest -q tests\test_stage122_channel_boundary.py --basetemp=.pytest_tmp_stage122
```
