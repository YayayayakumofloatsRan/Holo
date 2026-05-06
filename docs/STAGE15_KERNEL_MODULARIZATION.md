# Stage 15 Kernel Modularization

## Goal

Stage15 keeps Holo's calibrated subject-runtime behavior stable while making the reducer and policy core easier to iterate on. The work is structural, not feature-expanding.

## Boundary

- No new CLI or HTTP surface.
- No runtime contract change for WeChat identity, action-market-first deliberation, or operator safety.
- No new daemon loops.
- No live behavior drift unless covered by replay baseline updates and docs.

## Module Layout

- `holo_host/mind_graph.py` remains the public façade and DB host.
- `holo_host/mind_graph_parts/` now holds:
  - `state_defaults.py`
  - `outcome_appraisal.py`
  - `autobiographical_updates.py`
  - `goal_updates.py`
  - `schemas.py`
- `holo_host/memory_bridge.py` remains the public façade and packet orchestrator.
- `holo_host/policy_runtime/` now holds:
  - `action_simulation.py`
  - `action_market.py`
  - `counterfactuals.py`
  - `world_calibration_trace.py`
- `holo_host/reply_api.py` remains the service façade.
- `holo_host/reply_service_parts/` now holds:
  - `diagnostics.py`
  - `acceptance.py`
  - `artifacts.py`
  - `endpoints.py`

## Behavior Guardrails

- Stage14 replay remains the regression gate for policy and calibration behavior.
- Aggregate replay metrics should stay on the checked baseline within tight tolerance.
- Fixed-fixture action selection and best-available action expectations should remain stable.
- Calibration summaries and expression-budget decisions should stay snapshot-testable.

## Acceptance Checklist

- `pytest -q` passes.
- `pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py` passes.
- `python -m holo_host --config .holo_host.example.toml accept-stage14` passes.
- No `wechat:<name>` identity regression appears in replay or calibration tests.

## Rollback Notes

- If replay metrics drift unexpectedly, treat Stage15 as a structure regression and roll back the refactor modules before changing heuristics.
- If a helper module causes import-cycle failures, keep the façade file as the source of truth and re-extract in smaller pieces.
