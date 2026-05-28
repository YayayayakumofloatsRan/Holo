# Stage217 Operator Registry Dispatch

Stage217 turns the Stage216 market-operator bridge into a reusable operator registry.

## Problem

Stage216 proved the model-first loop can select and execute `market_research_operator_run`, but the reply runtime still had a dedicated branch for that one action. That does not scale to literature research, engineering operators, math/physics research, or future ProjectH operators.

## Implementation

- Added `holo_host/operator_registry.py`.
- Added schema `holo.stage217.operator_registry.v1` for operator definitions.
- Added schema `holo.stage217.operator_dispatch.v1` for dispatch reports.
- Registered `market_research_operator_run` as the first live operator.
- `tool_action_space.py` now receives operator action-space entries from the registry.
- `reply_api.py` dispatches model-selected operator actions through `dispatch_operator_action(...)` instead of a direct Stage215 branch.
- Operator dispatch returns capability-context updates, including Stage215 action, Stage214 run, web observations, source promotion, packs, reports, finalization gate, and action journal.
- `agent_event_stream.py` renders `[operator_dispatch]` rows before the existing `[market_operator]` trajectory.

## Runtime Contract

The loop remains:

```text
model selects operator action
host dispatches through registry
operator records ledgers
FSM observes required ledger
final answer is grounded or failure is reported
```

The registry is not a second brain. It is a host execution table for model-selected actions.

## Boundaries

- No hidden chain-of-thought or raw provider reasoning is exposed.
- No WeChat start or transport widening.
- No durable memory write.
- No destructive tool execution.
- Unknown operators are rejected with `boundary_or_permission`.
- Live market research still respects `runtime.network_enabled`; tests use deterministic dry-run fixtures.

## Verification

Verification:

```powershell
python -m pytest tests\test_stage217_operator_registry_dispatch.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage217-green
python -m pytest tests\test_stage217_operator_registry_dispatch.py tests\test_stage216_model_first_market_operator_action.py tests\test_stage215_market_research_operator_live_action.py tests\test_stage161_model_tool_arbitration.py tests\test_stage153_interactive_cli.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage217-targeted
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage217-runtime
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results: `5 passed`, `37 passed`, `92 passed`, `1055 passed`, public hygiene passed, and `git diff --check` exited 0 with CRLF normalization warnings only.
