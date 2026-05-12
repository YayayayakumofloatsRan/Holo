# Engineering Handoff Stage48

## Status

Stage48 adds a biomimetic memory scheduler over the existing Holo memory fabric. It does not add a new memory store. It separates memory material before prompt/context scheduling so provider calls receive a larger stable cortical prefix and a more explicit dynamic working/hippocampal payload.

Hard boundaries:

- WSL remains the authoritative subject kernel.
- Windows and watcher remain transport/history helpers only.
- The scheduler does not write self-memory.
- Consolidation targets are diagnostic intents for later bounded streams, not direct writes.
- Action-market authority remains unchanged.

## Architecture

The scheduler maps the existing `mind_packet` into five biomimetic surfaces:

- `working_memory`: current active thread state, temporal cues, residual factual guards, and dense reentry hints. This is volatile and prompt-dynamic.
- `hippocampal_index`: selected memory ids, activation motifs, episodic anchors, vector echoes, and recall reconstruction handles. This is volatile and prompt-dynamic.
- `cortical_schema`: stable identity lines, reply constraints, autobiographical chapter, stable traits, and active goal types. This is stable provider-prefix material.
- `salience_gate`: bounded score and recall budget derived from activation heat, explicit memory request, continuity anxiety, seek-continuity drive, prediction error, and temporal open loops.
- `consolidation_targets`: diagnostic labels such as `salient_turn`, `temporal_open_loop`, `reactivated_index`, and `semantic_reconstruction`, with `self_memory_write=false`.

## Modified Surfaces

- `holo_host/bionic_memory_scheduler.py`
  - Adds `build_bionic_memory_schedule(packet, query=...)`.
  - Produces deterministic, bounded scheduler output without touching storage.
- `holo_host/memory_bridge.py`
  - Attaches `bionic_memory_schedule` during `_finalize_stage2_packet()` after action/intention/state fields are available.
- `holo_host/processors.py`
  - Renders `Cortical Memory Schema` before dynamic chat/thread fields so it contributes to DeepSeek provider-cache prefix.
  - Renders `Working Memory`, `Hippocampal Index`, `Memory Salience Gate`, and `Bionic Memory Dynamic Context` inside dynamic prompt context.
  - Preserves scheduler metadata in processor debug.
- `holo_host/context_scheduler.py`
  - Accepts optional `memory_schedule`.
  - Reports `memory_schedule_mode`, `memory_schedule_stable_tokens`, `memory_schedule_dynamic_tokens`, and `memory_dynamic_pressure`.
- `holo_host/bionic_boundary_stress.py`
  - Compacts scheduler mode, salience score, recall budget, prefix line count, and dynamic line count into Stage46 evidence.

## Verification

Focused verification:

- `python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_memory_fabric.py tests\test_stage46_bionic_boundary_stress.py`: `30 passed`

Final verification:

- `python -m pytest -q`: `387 passed`
- `python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\memory_bridge.py holo_host\processors.py holo_host\context_scheduler.py holo_host\bionic_boundary_stress.py`: passed
- `python scripts\check_public_release_hygiene.py`: passed
- `git diff --check`: no whitespace errors; Git reported only CRLF conversion warnings for existing text files
- `python -m holo_host run-bionic-boundary-stress --thread-key cli:Stage48Offline-20260512 --chat-name Stage48Offline-20260512 --channel cli --turns 7 --offline`: `ok=true`, `overall_score=0.9889`, all Stage46 bionic correctness metrics `1.0`
- `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512W --chat-name DeepSeekLiveBoundary-20260512W --channel cli --turns 7`: `ok=true`, `overall_score=0.9635`, all Stage46 bionic correctness metrics `1.0`, `provider_substrate_score=1.0`, `provider_cache_hit_tokens=4608`, `prompt_cache_miss_tokens=18707`

## Empirical Finding

Compared with the previous live Stage46 run `cli:DeepSeekLiveBoundary-20260512V`, Stage48 increased estimated stable provider prefix tokens from `627` to `943` and live DeepSeek cache-hit tokens from `3200` to `4608` over seven turns. Dynamic prompt tokens also grew, so the next optimization is not simply adding more schema; it is increasing stable cortical schema only when it replaces volatile dynamic payload.
