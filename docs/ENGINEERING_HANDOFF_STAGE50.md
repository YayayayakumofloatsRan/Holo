# Engineering Handoff Stage50

## Status

Stage50 adds a scheduler-owned dynamic compression audit on top of the Stage49 memory prompt diet. The goal is to make dynamic memory pressure measurable and regression-testable before any future cortical-schema expansion or consolidation writeback is attempted.

Hard boundaries:

- WSL remains the authoritative subject kernel.
- Windows and watcher remain transport/history helpers only.
- No self-memory write path is added.
- No new memory store, provider call path, transport authority, or second decision layer is added.
- Action-market authority remains unchanged.

## Architecture Delta

- `holo_host/bionic_memory_scheduler.py`
  - Reorders working-memory candidates so low-salience budgets keep current state facts before route metadata.
  - Protects `active_summary`, `latest_user_intent`, `selected_action`, `temporal_resume_cue`, `reconstruction_summary`, and `anchor`.
  - Adds `prompt_dynamic_lines` as the scheduler-owned dynamic payload.
  - Adds `dynamic_compression_audit` with raw/selected/dropped line counts, compression ratio, budget reason, protected labels, and protected-drop status.
- `holo_host/context_scheduler.py`
  - Computes memory dynamic tokens from `prompt_dynamic_lines` rather than the older compiled duplicate field.
  - Exposes `memory_compression_mode`, `memory_prompt_dynamic_lines`, `memory_dropped_dynamic_lines`, `memory_compression_ratio`, `memory_protected_line_dropped`, and `memory_prompt_dynamic_tokens`.
- `holo_host/bionic_boundary_stress.py`
  - Compacts compression mode, prompt dynamic line count, dropped dynamic line count, and protected-drop status into Stage46 evidence.

## Verification

- `python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_memory_fabric.py tests\test_stage46_bionic_boundary_stress.py`: `37 passed`
- `python -m pytest -q`: `394 passed`
- `python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\context_scheduler.py holo_host\bionic_boundary_stress.py holo_host\processors.py holo_host\memory_bridge.py`: passed
- `python -m holo_host run-bionic-boundary-stress --thread-key cli:Stage50Offline-20260512 --chat-name Stage50Offline-20260512 --channel cli --turns 7 --offline`: `ok=true`, `overall_score=0.9886`, all Stage46 bionic correctness metrics `1.0`
- `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512Z --chat-name DeepSeekLiveBoundary-20260512Z --channel cli --turns 7`: `ok=true`, `overall_score=0.9647`, all Stage46 bionic correctness metrics `1.0`, `provider_cache_hit_tokens=5376`, `prompt_cache_miss_tokens=14525`

## Empirical Finding

Stage50 preserves Stage49's live correctness and cache profile while making the dynamic compression contract inspectable. The DeepSeek live run reported `memory_compression_mode=scheduler_owned_dynamic_v1` and `memory_protected_line_dropped=false` on every turn. Early turns compressed to seven scheduler dynamic lines while later high-salience turns expanded to eleven lines for reconstruction-heavy continuity without dropping protected labels.

The next safe direction is repeated live soak plus adaptive thresholds over the compression audit. Do not add consolidation-stream writeback or enlarge cortical schema until repeated live runs keep correctness, cache, and `protected_line_dropped=false` stable.
