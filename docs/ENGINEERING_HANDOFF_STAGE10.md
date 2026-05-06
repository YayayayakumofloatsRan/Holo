# Engineering Handoff: Stage-10 Live State

This document is the practical handoff for the next Holo thread after Stage-9.

## Snapshot
- Date: `2026-04-09`
- Repo of record: `D:\Holo\holo`
- Authoritative runtime repo: `/home/holo/holo`
- Current live stage: `Stage-9`
- Next stage focus: `Stage-10 engineering awareness`
- Current brain mode: `full_brain`
- Current transport: `pyweixin_dialog`
- Current active processor: `codex_cli`

## Stage-10 Goal
- turn engineering state into a first-class subject signal
- make cost, routing, provider health, cache warmth, and operator delta visible to the subject kernel
- keep the watcher as transport only
- keep the processor fabric as the only model-call path

## Core Principle
- the subject should be able to diagnose its own runtime bottlenecks without becoming a second decision-maker
- engineering awareness must flow into goal arbitration and bounded repair, not around them
- cost must stay attributable to lanes, providers, and tasks
- self-repair should be delta-gated, not timer-driven in steady state

## Scope Boundaries
Do:
- extend `self_model` and `homeostasis` with engineering snapshots
- let engineering signals conditionally enter `goal_state`
- record trigger deltas and expected state gains for operator cycles
- preserve existing stage-8 and stage-9 behavior

Do not:
- add watcher-side decision logic
- add direct CLI or raw HTTP model calls outside the provider abstraction
- bypass `/reply`, `/ingest-artifact`, or path normalization contracts
- let `operator_bus` become a free-running planner without meaningful state change

## Expected Data Contract
- `self_model.metadata.engineering_snapshot`
- `homeostasis_state.provider_state`
- `homeostasis_state.routing_state`
- `homeostasis_state.usage_state`
- `homeostasis_state.cache_state`
- `homeostasis_state.operator_state`
- `goal_state.active_goals[]` may include engineering goals such as:
  - `cost_discipline`
  - `routing_resilience`
  - `cache_warmth`
  - `expression_calibration`
- `operator_run.payload/result` must carry:
  - `trigger_delta`
  - `source_goal_ids`
  - `expected_state_gain`
  - `budget_guard`
- consciousness ledger entries should retain the engineering trace that led to a repair or plan

## Acceptance Checklist
- `engineering_state_visible`
- `provider_routing_usage_visible`
- `engineering_deficits_specific`
- `engineering_goals_enter_arbitration`
- `operator_is_delta_gated`
- `operator_plan_explains_trigger_and_budget_guard`
- `consciousness_ledger_carries_engineering_trace`
- `usage_ledger_records_stage10_tasks`
- `no_fabric_bypass`
- `ordinary_reply_path_not_regressed`

## Deployment / Rollback
- keep the watcher and transport untouched
- keep Stage-9 gates and contracts passing
- prefer additive snapshots and new read-only observability before changing runtime selection logic
- if engineering goals start crowding out relationship continuity, roll back the goal weighting first, not the data capture

## Read Order For A New Thread
1. `HOLO_HANDOFF.md`
2. `docs/HANDOFF_CHECKLIST.md`
3. `docs/HOLO_ARCHITECTURE_MAP.md`
4. `docs/WHEEL_CATALOG.md`
5. `docs/PROCESSOR_ROUTING_AND_COST_POLICY.md`
6. `docs/PROVIDER_COMPATIBILITY_CONTRACT.md`
7. `docs/WECHAT_WATCHER_INTERFACE_CONTRACT.md`
8. `docs/STAGE10_ENGINEERING_AWARENESS_AND_CODEX_COST.md`
9. `docs/STAGE9_INTELLIGENCE_AND_CODEX_COST.md`
10. `docs/ENGINEERING_HANDOFF_STAGE9.md`
11. `HOLO_SYSTEM.md`
12. `HOLO_HOST.md`
13. `OPERATIONS.md`

## Exit Criteria
- engineering state is visible enough to diagnose runtime pressure without guesswork
- engineering targets can enter goal arbitration without becoming a second brain
- operator cycles only fire when the state delta is meaningful
- Stage-8 and Stage-9 contracts still pass
