# Stage28 Multimodal Homeostatic Kernel

## What Stage28 Adds

Stage28 adds a bounded situational-field layer over the existing Stage24 scene state, Stage25 dense continuity, Stage26 task-world state, and visual memory.

It does not add:

- a second brain
- a new always-on loop
- transport-side decision logic
- new send rights
- direct provider calls outside the processor fabric

It does add:

- `mind_packet.visual_field`
- `mind_packet.situational_field`
- `mind_packet.stage28`
- richer visual metadata for image understanding
- inspectable Stage28 action-market deltas
- diagnostics for situational field, visual field, and inquiry shaping
- `accept-stage28`

## Runtime Contract

`situational_field` is a derived packet surface, not a new memory store.

The grounding order is:

1. `visual_field`
2. `scene_state`
3. `task_world`
4. `dense_working_set`
5. `temporal_state`
6. optional recent history

The field may nudge action-market scores, but it cannot pick or send independently. Hard recall, factual, safety, transport, canary, and operator gates remain outside Stage28.

## Visual Field

Image ingest now asks the processor fabric for compact visual state:

- `scene_summary`
- `objects`
- `text_ocr`
- `mood_imagery`
- `thread_relevance`
- `visual_anchors`
- `spatial_refs`
- `uncertainty_markers`
- `revisit_needed`
- `perceptual_density`

The extra fields are stored in visual-memory metadata and projected through `visual_field`. They are used to shape grounded follow-up questions instead of generic clarification templates.

## Action Market

Stage28 applies a small bounded overlay after simulation and scene overlays, before policy sedimentation.

Every candidate exposes:

- `stage28_delta`
- `stage28_rationale`
- `stage28_grounding_order`

The overlay is capped and inspectable. It boosts compact grounded replies when visual uncertainty or situational continuity is visible, and it preserves hard gates by recording rationale without overriding them.

## Diagnostics

```bash
python -m holo_host show-situational-field --thread-key TestUser --chat-name TestUser --channel wechat --query "continue"
python -m holo_host trace-visual-field --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host trace-inquiry-shaping --thread-key TestUser --chat-name TestUser --channel wechat --query "continue"
```

HTTP mirrors:

- `/situational-field`
- `/visual-field`
- `/inquiry-shaping`

## Acceptance

```bash
pytest -q tests/test_stage28_multimodal_homeostatic_kernel.py
python -m holo_host --config .holo_host.example.toml accept-stage28 --thread-key TestUser --chat-name TestUser --channel wechat
```

`accept-stage28` calls `accept-stage27` first, seeds a bounded visual/task-world/scene probe, verifies situational prompt ordering before history, verifies visual uncertainty shapes grounded inquiry, verifies explicit memory queries still escalate, and verifies no self-memory mutation.

## Guardrails

- Stage28 is packet-derived and bounded.
- Visual state remains inspectable and compact.
- Explicit memory/history/factual turns still escalate.
- Action-market-first deliberation remains the only decision path.
- No runtime code path in Stage28 may start a new watcher, daemon, loop family, or transport decision surface.
