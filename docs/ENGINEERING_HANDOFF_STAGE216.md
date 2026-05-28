# Engineering Handoff Stage216

## Summary

Stage216 makes the full market-research operator a model-first executable action. The model can now select `market_research_operator_run` from the structured action space, the host executes Stage215/Stage214, the FSM observes the Stage214 ledger, and the CLI event stream can show the resulting market-operator trajectory.

## Files Changed

- `holo_host/tool_action_space.py`
- `holo_host/model_tool_arbitration.py`
- `holo_host/agent_loop_fsm.py`
- `holo_host/market_research_operator_live_action.py`
- `holo_host/reply_api.py`
- `tests/test_stage216_model_first_market_operator_action.py`
- `docs/STAGE216_MODEL_FIRST_MARKET_OPERATOR_ACTION.md`
- `docs/ENGINEERING_HANDOFF_STAGE216.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## Runtime Propagation

- Action space exposes `market_research_operator_run`.
- Stage152-derived arbitration maps the action to `stage214_market_research_operator_run`.
- Reply API runs Stage215/214 after Stage161 arbitration when the model selects the operator.
- FSM records the operator action as executed only when Stage214 status is `ready`.
- Final text can be replaced by Stage214 `final_visible_text`.
- Stage153 trace continues rendering `[model_decide]` and `[market_operator]` rows.

## Constraints Preserved

- Hidden reasoning remains private.
- Provider internals are sanitized before public JSON/archive/CLI surfaces.
- Network behavior still respects runtime configuration.
- No WeChat start, transport widening, durable memory write, or destructive tool action was added.

## Test Results

Completed commands:

```powershell
python -m pytest tests\test_stage216_model_first_market_operator_action.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage216-green
python -m pytest tests\test_stage216_model_first_market_operator_action.py tests\test_stage215_market_research_operator_live_action.py tests\test_stage161_model_tool_arbitration.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage216-targeted
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage216-runtime
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results: `5 passed`, `23 passed`, `92 passed`, `1050 passed`, public hygiene passed, and `git diff --check` exited 0 with CRLF normalization warnings only.

## Next Suggested Stage

Stage217 should extend the same model-first execution bridge to a general operator registry so future research/engineering/domain operators can be selected by the model and executed through one host controller instead of per-action wiring.
