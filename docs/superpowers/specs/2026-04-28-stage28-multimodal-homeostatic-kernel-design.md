# Stage28 Multimodal Homeostatic Kernel Design

## Goal
Stage28 makes Holo's next arc explicit: move from text-led continuity layers to a bounded multimodal situational kernel that can fuse text, visual memory, scene state, dense continuity, temporal pressure, and task-world state before deciding how to speak, ask, wait, or recall.

## Non-Negotiable Boundaries
- No runtime startup or watcher changes in this implementation.
- No second brain layer.
- No new unbounded always-on loop.
- No transport-side decision logic.
- No direct model/API calls outside the processor fabric.
- Memory remains self; processors remain replaceable; transport remains eyes and hands.
- Action-market-first deliberation remains the decision path.

## Architecture
Stage28 adds a derived `situational_field` in `MemoryBridge` and exposes it through `mind_packet.stage28`. The field is not a planner and not a new memory store. It is a bounded synthesis layer over existing state:
- `visual_memory`
- `scene_state`
- `dense_working_set`
- `temporal_subject_state`
- `task_world_object`
- active subject affect/drive/value/conflict state

The field produces compact, inspectable state:
- current field summary
- visible modalities
- grounding order
- open questions
- visual field and uncertainty
- non-template inquiry hint
- history reliance estimate
- hard gate preservation status

## Visual Design
Visual processing remains inside processor fabric through `image_understand`. Stage28 widens the visual payload format without requiring a Mind Graph schema migration. Extra visual details live in `visual_memory.metadata`:
- `spatial_refs`
- `uncertainty_markers`
- `revisit_needed`
- `perceptual_density`

`visual_memory_state()` and `mind_packet.visual_field` surface these details. The prompt can then refer to visual uncertainty as a grounded reason to ask, rather than producing a generic clarification template.

## Initiative And Expression Design
Stage28 does not grant new send rights. It adds a small action-market overlay that annotates candidates with:
- `stage28_delta`
- `stage28_rationale`
- `stage28_grounding_order`

The overlay only nudges existing candidates. It favors a compact grounded reply when the situation contains a clear open question, especially when the question comes from visual uncertainty or task-world/scene pressure. It preserves explicit memory, factual, search, visual recall, canary, cooldown, whitelist, and rollback gates.

## Diagnostics
New diagnostics should expose the kernel state without starting Holo:
- `show-situational-field --thread-key ... --query ...`
- `trace-visual-field --thread-key ...`
- `trace-inquiry-shaping --thread-key ... --query ...`
- `accept-stage28`

## Acceptance
`accept-stage28` calls `accept-stage27` first, seeds a bounded visual/task-world/scene probe, verifies prompt ordering and action-market annotations, verifies explicit memory escalation, and confirms no self-memory mutation occurs during the Stage28 probe.

