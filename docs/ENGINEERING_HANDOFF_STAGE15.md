# Stage15 Engineering Handoff

## What Landed

- `MindGraph`, `MemoryBridge`, and `HoloReplyService` remain the stable public façades.
- Large reducer/policy logic is now split into `mind_graph_parts`, `policy_runtime`, and `reply_service_parts`.
- Shared heuristic/default bundles now have a typed home in `holo_host/policies.py`.
- Stage15 adds replay-preserving regression coverage in `tests/test_stage15_modularization.py`.

## Rerun Commands

- `pytest -q`
- `pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage14`

## Expected Replay Baseline

- `response_quality_mae`: `0.3011`
- `relational_delta_mae`: `0.1681`
- `risk_mae`: `0.1182`
- `false_initiative_block_rate`: `0.25`
- `overlong_reply_rate`: `0.25`
- `stiffness_overflow_rate`: `0.25`
- `cost_per_successful_turn`: `755.0`
- `policy_regret_vs_best_available_action`: `0.0613`

## File Ownership After Stage15

- Keep `holo_host/mind_graph.py` focused on persistence façade, schema, and delegating entrypoints.
- Keep `holo_host/memory_bridge.py` focused on orchestration and packet assembly.
- Keep `holo_host/reply_api.py` focused on service façade and route wiring.
- Put future reducer/policy changes in the extracted helper packages first unless the public façade contract changes.

## Next Focus

- Continue shrinking façade files by moving remaining dead-weight helper blocks only when replay baselines stay stable.
- Unify duplicated reply/persona constant bundles under `holo_host/policies.py` in another behavior-preserving pass.
