# Stage216 Model-First Market Operator Action

Stage216 connects the complete Stage214 market-research operator to the Stage161 model-first action space.

## Problem

Stage215 could execute the market-research operator from host-side prompt detection, but a model-selected `market_research_operator_run` was still not a first-class executable action. The FSM saw the selection as an unimplemented action, so the loop could stop with a clarification-style failure even when Stage214 had already produced a ready operator run.

## Implementation

- `tool_action_space.py` now exposes `market_research_operator_run` as a read-only, network-requiring action whose required observation is `stage214_market_research_operator_run`.
- `model_tool_arbitration.py` maps DeepSeek/Stage152 tool calls named `market_research_operator_run` to the Stage214 observation requirement.
- `reply_api.py` executes Stage215/Stage214 when Stage161 arbitration selects `market_research_operator_run`, before the final FSM evaluation.
- `agent_loop_fsm.py` treats the Stage215 action report and Stage214 operator run as auditable observations. A ready Stage214 run closes with `final_answer_ready`; rejected or failed runs close with boundary/tool-failure stop reasons.
- Stage153 already renders `[market_operator]` rows from the Stage214 trajectory, so the live CLI can show action phases without exposing hidden reasoning.

## Boundaries

- No raw hidden chain-of-thought or provider `reasoning_content` is exposed.
- The public trace may show goals, model decision summaries, action selection, observations, evaluation, stop reasons, and final text.
- No new memory write path, WeChat start, transport authority, or destructive engineering action is added.
- Dry-run fixtures remain deterministic for tests; live operation still respects `runtime.network_enabled`.

## Verification

Verification:

```powershell
python -m pytest tests\test_stage216_model_first_market_operator_action.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage216-green
python -m pytest tests\test_stage216_model_first_market_operator_action.py tests\test_stage215_market_research_operator_live_action.py tests\test_stage161_model_tool_arbitration.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage216-targeted
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage216-runtime
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results: `5 passed`, `23 passed`, `92 passed`, `1050 passed`, public hygiene passed, and `git diff --check` exited 0 with CRLF normalization warnings only.
