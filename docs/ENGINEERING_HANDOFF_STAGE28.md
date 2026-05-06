# Stage28 Engineering Handoff

## Implemented Change

Stage28 adds a multimodal situational kernel that fuses visual memory, scene state, dense continuity, task-world state, temporal pressure, and homeostatic/affective pressure into one bounded packet surface.

The live rule is:

- visual and task-world evidence can shape ordinary continuation before verbatim history
- grounded inquiry must refer to concrete visible uncertainty or unresolved scene/task evidence
- Stage28 can bias the action market, but never bypass it
- no new loop, no second store, no transport-side decision path

## Runtime Surfaces

- `holo_host/memory_bridge.py`
  - adds `visual_field`, `situational_field`, and `stage28` to finalized mind packets
  - exposes `show_situational_field(...)`, `trace_visual_field(...)`, and `trace_inquiry_shaping(...)`
  - stores extended visual-understanding metadata through visual memory
- `holo_host/policy_runtime/action_market.py`
  - adds `apply_situational_field_overlay(...)`
  - annotates candidates with Stage28 deltas and rationale
- `holo_host/processors.py`
  - renders `Situational Field:` before `Recent Thread Window:`
  - adds an anti-template instruction for grounded follow-up questions
- `holo_host/reply_api.py`
  - adds service and HTTP diagnostics
  - adds `accept_stage28(...)`
- `holo_host/cli.py`
  - adds:
    - `show-situational-field`
    - `trace-visual-field`
    - `trace-inquiry-shaping`
    - `accept-stage28`
- `tests/test_stage28_multimodal_homeostatic_kernel.py`
  - covers packet fusion, visual metadata preservation, prompt ordering, and action-market inspectability

## Acceptance Checks

`accept-stage28` verifies:

- Stage27 acceptance remains green
- `situational_field` and `visual_field` are visible
- visual uncertainty shapes grounded inquiry
- `Situational Field:` appears before any recent-history block
- Stage28 action-market overlay fields are inspectable
- explicit memory queries still escalate
- diagnostics return usable payloads
- self-memory is not mutated by the Stage28 probe
- no second-brain or unbounded-loop flags are introduced

## Commands

```bash
python -m holo_host show-situational-field --thread-key TestUser --chat-name TestUser --channel wechat --query "continue"
python -m holo_host trace-visual-field --thread-key TestUser --chat-name TestUser --channel wechat
python -m holo_host trace-inquiry-shaping --thread-key TestUser --chat-name TestUser --channel wechat --query "continue"
python -m holo_host --config .holo_host.example.toml accept-stage28 --thread-key TestUser --chat-name TestUser --channel wechat
```

## Review Notes

- Stage28 is intentionally a vertical slice, not the whole post-Stage27 reform.
- API-provider adaptation is still constrained to processor-fabric call sites.
- Runtime image reading now has a richer contract, but real provider coverage still depends on configured `image_understand` lanes.
- Holo should remain offline until the larger reform plan explicitly decides how to restart and test watcher transport.

## Next Step

Stage29 should be explicitly re-planned. Likely targets are provider/API compatibility breadth, visual-provider hardening, and less template-shaped inquiry generation, but none of those are automatically in scope from Stage28.
