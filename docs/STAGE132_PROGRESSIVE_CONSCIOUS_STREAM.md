# Stage132 Progressive Conscious Stream

Stage132 turns the fast provider packet into the first round of a visible stream instead of treating it as a terminal shortcut.

## Practical Contract

For one user input `A`, Holo now models the response as a packet sequence:

1. `round 0`: `micro_fast` / flash lane. It receives a richer bounded context frame, judges intent and scene, and may emit a visible first reaction `A'`.
2. `round 1`: `subject_main` or upgraded pro lane when the fast packet marks the turn as deep, uncertain, tool-grounded, memory-related, or self-model related. It emits the deeper continuation `A''`.
3. Tool loops remain inside the deep lane metadata and are shown as part of the stream when provider tools are expected.

The fast packet is therefore not proof that the thought loop is complete. It is a first biological-style reflex plus a triage packet.

## Fast Context Frame

`build_stage132_fast_context_frame` builds a bounded high-priority prefix for the fast packet:

- selected action and uncertainty
- attention focus and pressure
- active-thread continuity and scene frame
- short-term working memory constraints
- recent dialogue
- declared tool requests
- current user text

The frame is capped and gets a stable `stage132:*` cache hint. This is meant to make the first packet sufficiently contextual while keeping the provider prefix cacheable.

## External Stream Preservation

`merge_stage132_reply_bubbles` preserves `A'` and `A''` as distinct bubbles for CLI and app channels. `reply_api` now honors Stage132 planned bubbles instead of rebuilding them into one generic bubble.

This makes the user-visible behavior match the underlying packet flow:

```text
A
A'
A''
```

## CT Visibility

`trace-thought-flow` now renders Stage132 stream metadata when present:

```text
STAGE132 STREAM rounds=2 cache=stage132:... context_lines=...
ROUND 0 lane=micro_fast purpose=fast_reaction visible=yes
ROUND 1 lane=subject_main purpose=deep_continuation visible=yes
```

The companion static CT artifact is:

`artifacts/stage132/stage132_progressive_conscious_stream_ct.html`

It visualizes the same contract as a topology: input, working memory, episodic recall, flash packet, intent gate, tool loop, pro packet, and output stream.
