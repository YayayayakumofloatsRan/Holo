# Stage50 Dynamic Compression Audit Plan

## Goal

Finish the next memory-architecture improvement by making scheduler-owned dynamic memory compression observable, testable, and safe under DeepSeek live pressure.

## Constraints

- WSL subject runtime remains authoritative.
- Windows and watcher remain transport/history helpers only.
- No self-memory writes, no new memory store, no transport widening, no second decision layer.
- Dynamic compression may reduce prompt payload only when protected recall/current-state lines remain visible.

## Implementation Steps

1. Add failing tests for low-salience working-memory prioritization.
2. Add failing tests for `dynamic_compression_audit`.
3. Add failing tests for context-scheduler and Stage46 compact debug visibility.
4. Reorder working-memory candidates so current state outranks route metadata.
5. Add scheduler-owned prompt dynamic lines and compression audit fields.
6. Route context-scheduler memory token accounting through `prompt_dynamic_lines`.
7. Verify with focused tests, full tests, offline Stage46, and DeepSeek live Stage46.

## Acceptance Evidence

- Focused memory/context/stress tests pass.
- Full test suite passes.
- Offline Stage46 passes with all bionic correctness metrics at `1.0`.
- DeepSeek live Stage46 passes with all bionic correctness metrics at `1.0`.
- Stage46 evidence shows `memory_compression_mode=scheduler_owned_dynamic_v1` and `protected_line_dropped=false`.
