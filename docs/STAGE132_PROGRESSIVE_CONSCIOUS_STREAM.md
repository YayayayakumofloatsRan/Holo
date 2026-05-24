# Stage132 Progressive Conscious Stream

Stage132 turns the fast provider packet into the first round of a visible stream instead of treating it as a terminal shortcut.

## Practical Contract

For one user input `A`, Holo now models the response as a provider-governed packet sequence:

1. `round 0`: `micro_fast` / flash lane. It receives a richer bounded context frame, judges intent and scene, and may emit a visible first reaction `A'`.
2. `round 1+`: optional continuation rounds. They exist only when the fast packet marks the turn as needing more work; the host must not create them as a fixed script.
3. Tool loops remain inside continuation metadata and are shown as part of the stream only when provider tools are expected.

The fast packet is therefore not proof that the thought loop is complete. It is a first biological-style reflex plus a triage packet.
The continuation decision source is the provider fast packet: `deep_packet_needed=true/false`.
Host-side heuristics may add `host_deep_advisory=true` for diagnostic visibility, but they must not force a visible continuation by themselves.

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

`merge_stage132_reply_bubbles` preserves the first reaction and any optional continuation as distinct bubbles for CLI and app channels. `reply_api` now honors Stage132 planned bubbles instead of rebuilding them into one generic bubble.

Stage142 now gates this merge path. The continuation bubble is still provider-requested, but it is emitted only when it adds useful semantic novelty, grounded evidence, task progress, an explicit correction, or a meaningful limitation. Duplicate, low-value, contradictory, or ungrounded continuations are trimmed or suppressed before delivery and archive.

This makes the user-visible behavior match the underlying packet flow:

```text
A
A'
optional continuation only if the fast packet asks for it
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

It visualizes the same contract as a topology: input, working memory, episodic recall, flash packet, intent gate, optional tool loop, optional continuation packet, and output stream.
