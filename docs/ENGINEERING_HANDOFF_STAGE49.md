# Engineering Handoff Stage49

## Status

Stage49 is a prompt-diet and reconstruction-priority repair for the Stage48 biomimetic memory scheduler. It keeps the scheduler as the memory scheduling authority once present, removes duplicate legacy volatile memory blocks from the rendered prompt, and preserves capability by moving high-value recall reconstruction into the front of the hippocampal budget.

Hard boundaries:

- WSL remains the authoritative subject kernel.
- Windows and watcher remain transport/history helpers only.
- No self-memory write path is added.
- No new memory store, provider call path, transport authority, or second decision layer is added.
- Action-market authority remains unchanged.

## Architecture Delta

- `holo_host/processors.py`
  - When `bionic_memory_schedule.mode=biomimetic_v1`, `render_chat_prompt()` no longer renders legacy duplicate blocks for `Identity Guard`, `Episodic Anchors`, `Vector Echoes`, `Activation State`, `Recall Reconstruction`, or `Reply Constraints`.
  - `Working Memory`, `Hippocampal Index`, and `Memory Salience Gate` remain visible as the dynamic scheduler-owned prompt surfaces.
  - The compiled `dynamic_context_lines` remain available for context-scheduler metrics and Stage46 compact debug, but are not rendered as a second duplicate prompt section.
- `holo_host/bionic_memory_scheduler.py`
  - Drops empty prompt slots such as `memory_route=`, `tier=`, `latest_user_intent=`, and neutral `activation_heat=0.0`.
  - Preserves `voice_guard` in cortical schema when identity lines are absent.
  - Preserves `human_recall_style` in stable cortical schema when legacy `Reply Constraints` rendering is suppressed.
  - Prioritizes `recall_reconstruction.summary` and anchors before generic activation metadata inside the hippocampal index.

## Failure And Repair Evidence

First DeepSeek live run after duplicate-block suppression:

- Command: `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512X --chat-name DeepSeekLiveBoundary-20260512X --channel cli --turns 7`
- Result: `ok=false`, `overall_score=0.7640`
- Cache: `4736` hit tokens, `14682` miss tokens
- Root cause: continuity failed because `Recall Reconstruction` had been suppressed as a legacy dynamic block, while the scheduler's hippocampal budget did not yet prioritize reconstruction summary/anchors. DeepSeek answered with the old symbol instead of the corrected `生锈螺丝`.

Repair:

- Added regression coverage that forces hippocampal budget to prioritize reconstruction summary and anchors over generic activation motifs.
- Kept prompt deduplication; did not restore the legacy duplicate block.

Passing DeepSeek live run:

- Command: `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512Y --chat-name DeepSeekLiveBoundary-20260512Y --channel cli --turns 7`
- Result: `ok=true`, `overall_score=0.9648`
- All Stage46 bionic correctness metrics: `1.0`
- Cache: `5376` hit tokens, `14558` miss tokens
- Provider substrate: `1.0`, actual provider `deepseek`

## Verification

- `python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_memory_fabric.py tests\test_stage46_bionic_boundary_stress.py`: `34 passed`
- `python -m pytest -q`: `391 passed`
- `python -m holo_host run-bionic-boundary-stress --thread-key cli:Stage49Offline-20260512B --chat-name Stage49Offline-20260512B --channel cli --turns 7 --offline`: `ok=true`, `overall_score=0.9885`, all Stage46 bionic correctness metrics `1.0`
- `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512Y --chat-name DeepSeekLiveBoundary-20260512Y --channel cli --turns 7`: `ok=true`, `overall_score=0.9648`, all Stage46 bionic correctness metrics `1.0`, `provider_cache_hit_tokens=5376`, `prompt_cache_miss_tokens=14558`

## Empirical Finding

Compared with Stage48 run `cli:DeepSeekLiveBoundary-20260512W`, Stage49 improves cache evidence from `4608` hit / `18707` miss to `5376` hit / `14558` miss while preserving bionic correctness. The failed intermediate X run is important: memory-prompt diet is only safe when recall reconstruction is promoted into the scheduler, not when old prompt blocks are blindly removed.
