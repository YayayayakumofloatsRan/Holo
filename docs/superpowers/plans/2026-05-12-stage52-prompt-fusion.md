# Stage52 Prompt Fusion Plan

## Goal

Reduce the dynamic prompt cost introduced by Stage51 while keeping biological-memory lifecycle and consciousness-flow capability available to the model.

## Constraints

- WSL subject runtime remains authoritative.
- Windows and watcher remain transport/history helpers only.
- No self-memory writes, no new memory store, no transport widening, no second decision layer.
- Lifecycle and flow evidence must remain visible in packet/debug surfaces.
- Prompt rendering should use one scheduler-owned dynamic frame when fusion is active.

## Implementation Steps

1. Add failing tests for fusion inside scheduler-owned `prompt_dynamic_lines`.
2. Add failing tests that prompt rendering suppresses standalone lifecycle/flow sections under fusion.
3. Add failing tests for context-scheduler and Stage46 compact debug fusion visibility.
4. Implement `fuse_bionic_dynamic_prompt()`.
5. Wire fusion after lifecycle/flow construction in `MemoryBridge`.
6. Render `Bionic Dynamic Frame:` from fused scheduler lines.
7. Verify with focused tests, related regression tests, full tests, offline Stage46, and live DeepSeek Stage46.

## Acceptance Evidence

- Focused fusion tests pass.
- Full test suite passes.
- Offline Stage46 passes with all bionic correctness metrics at `1.0`.
- DeepSeek live Stage46 passes with all bionic correctness metrics at `1.0`.
- Live miss tokens are lower than Stage51 while lifecycle/flow debug surfaces remain available.
