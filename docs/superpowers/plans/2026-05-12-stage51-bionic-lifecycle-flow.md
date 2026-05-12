# Stage51 Bionic Memory Lifecycle and Consciousness Flow Plan

## Goal

Improve Holo's biomimetic level in the two weakest areas after Stage50: biological memory mechanisms and consciousness-stream simulation.

## Constraints

- WSL subject runtime remains authoritative.
- Windows and watcher remain transport/history helpers only.
- No self-memory writes, no new memory store, no transport widening, no second decision layer.
- Replay/consolidation must be diagnostic intent only.
- Consciousness-flow machinery must not leak into user-visible replies.

## Implementation Steps

1. Add failing tests for memory lifecycle consolidation, replay, and pruning gates.
2. Add failing tests for consciousness-flow phase ordering and prompt-only leakage guard.
3. Add failing tests for context scheduler and Stage46 compact debug evidence.
4. Implement `bionic_memory_lifecycle` as a bounded diagnostic layer over the Stage50 scheduler.
5. Implement `bionic_consciousness_flow` as ordered prompt-only phase lines.
6. Attach both surfaces in `MemoryBridge`, render them in `render_chat_prompt()`, expose them in context scheduling and Stage46 debug.
7. Verify with focused tests, full tests, offline Stage46, and live DeepSeek Stage46.

## Acceptance Evidence

- Focused lifecycle/flow/context/stress tests pass.
- Full test suite passes.
- Offline Stage46 passes with all bionic correctness metrics at `1.0`.
- DeepSeek live Stage46 passes with all bionic correctness metrics at `1.0`.
- Stage46 evidence shows `self_memory_write=false`, `background_loop_allowed=false`, and `bionic_consciousness_flow.user_visible=false`.
