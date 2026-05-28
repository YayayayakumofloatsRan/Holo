# Engineering Handoff Stage217

## Summary

Stage217 adds a general operator registry and dispatch layer. The first registered live operator is `market_research_operator_run`, but the interface is now reusable for future literature, engineering, math, physics, market, and ProjectH operators.

## Files Changed

- `holo_host/operator_registry.py`
- `holo_host/tool_action_space.py`
- `holo_host/reply_api.py`
- `holo_host/agent_event_stream.py`
- `tests/test_stage217_operator_registry_dispatch.py`
- `docs/STAGE217_OPERATOR_REGISTRY_DISPATCH.md`
- `docs/ENGINEERING_HANDOFF_STAGE217.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schemas

- `holo.stage217.operator_registry.v1`
- `holo.stage217.operator_dispatch.v1`

## Runtime Propagation

- Operator definitions produce action-space entries.
- Stage161 model arbitration can select registered operator actions.
- Reply runtime calls `dispatch_operator_action(...)`.
- Dispatch reports are propagated into sidecar/debug/reply/archive metadata.
- Capability updates from dispatch are fed back into the existing Stage214/215 market operator path.
- Stage153 renders `[operator_dispatch]` rows, followed by existing `[market_operator]` rows.

## Constraints Preserved

- Hidden reasoning remains private.
- Unknown operators are rejected, not guessed.
- Network-gated operators still respect runtime network configuration.
- No WeChat start, transport widening, memory mutation, or destructive tool action was introduced.

## Test Results

Completed commands:

```powershell
python -m pytest tests\test_stage217_operator_registry_dispatch.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage217-green
python -m pytest tests\test_stage217_operator_registry_dispatch.py tests\test_stage216_model_first_market_operator_action.py tests\test_stage215_market_research_operator_live_action.py tests\test_stage161_model_tool_arbitration.py tests\test_stage153_interactive_cli.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage217-targeted
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage217-runtime
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results: `5 passed`, `37 passed`, `92 passed`, `1055 passed`, public hygiene passed, and `git diff --check` exited 0 with CRLF normalization warnings only.

## Next Suggested Stage

Stage218 should add a second real registered operator, preferably a literature/web-research operator that uses the Stage186 crawler and Stage212 action journal without market-specific assumptions.
