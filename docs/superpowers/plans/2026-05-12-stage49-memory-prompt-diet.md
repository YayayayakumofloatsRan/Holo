# Stage49 Memory Prompt Diet Plan

## Goal

Make Stage48's biomimetic memory scheduler replace volatile prompt material instead of adding more prompt material, while preserving continuity under DeepSeek live pressure.

## Constraints

- WSL-side subject runtime remains authoritative.
- Windows and watcher remain transport/history helpers only.
- No self-memory writes, no new store, no second brain, no transport widening.
- Provider caching is evidence, not authority.

## Implementation Steps

1. Add regression tests that fail while scheduler-owned memory still duplicates legacy volatile prompt blocks.
2. Suppress legacy memory blocks when `bionic_memory_schedule.mode=biomimetic_v1`.
3. Keep compatibility by migrating `voice_guard` and `human_recall_style` into stable cortical schema.
4. Drop empty scheduler slots from prompt surfaces.
5. Use DeepSeek live failure evidence to identify reconstruction loss rather than reverting prompt diet.
6. Prioritize `recall_reconstruction.summary` and anchors at the front of hippocampal budget.
7. Verify with focused tests, full tests, offline Stage46, and live DeepSeek Stage46.

## Acceptance Evidence

- Focused scheduler/context/stress tests pass.
- Full test suite passes.
- Offline Stage46 passes.
- DeepSeek live Stage46 passes with all bionic correctness metrics at `1.0`.
- Cache hit tokens improve and miss tokens fall relative to Stage48 W without restoring duplicate prompt blocks.
