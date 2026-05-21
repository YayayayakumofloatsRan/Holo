# Progress 2026-05-22: Stage104 Context Learning

## Goal

Make Holo's memory system less like recent-log replay and more like local context learning: short-term activity is compressed into durable semantic attractors, then injected into the provider context packet.

## Changes

- Added `holo_host/stage104_context_learning.py`.
- Added CLI command `stage104-context-learning`.
- Injected Stage104 attractor lines in `MemoryBridge._finalize_stage2_packet()`.
- Exposed `stage104` and `semantic_attractor_lines` in `inspect_mind`.
- Added `context_attractor` as a prompt-eligible memory kind in `holo_memory_library/rag_memory.py`.
- Added focused tests in `tests/test_stage104_context_learning.py`.

## Live Check

Commands used:

```powershell
pytest -q tests\test_stage104_context_learning.py --basetemp .holo_runtime\pytest-stage104
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host stage104-context-learning --repo-root /home/holo/holo --dry-run --query '回忆任何事情？' --attractor-limit 5"
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host stage104-context-learning --repo-root /home/holo/holo --apply --confirm APPLY_STAGE104_CONTEXT_LEARNING_FROM_WSL --query '回忆任何事情？' --attractor-limit 5"
```

Observed:

- Focused Stage104 tests passed: `4 passed`.
- Live WSL dry-run found 5 attractors.
- Live WSL apply wrote 5 candidates.
- Mind-packet inspection showed `context_learning_visible=true` and Stage104 attractor lines before the recent recall echo.
- Durable memory now includes Stage104 attractor rows `memory-0023` through `memory-0027`.

## Guardrails

- No WeChat watcher was started.
- No memory reset was run.
- Stage104 apply requires WSL and exact confirmation `APPLY_STAGE104_CONTEXT_LEARNING_FROM_WSL`.
- The live `/home/holo/holo` checkout is dirty, so code sync to that checkout was not attempted.
