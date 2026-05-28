# Engineering Handoff Stage218

## Summary

Stage218 registers `web_research_operator_run` as a domain-neutral live web/literature research operator. It reuses Stage186 crawler and Stage212 action journal, then feeds `stage218_web_research_operator_run` into the existing model-first operator dispatch, FSM, reply metadata, CLI event stream, and Stage135 topology.

## Files Changed

- `holo_host/web_research_operator.py`
- `holo_host/operator_registry.py`
- `holo_host/model_tool_arbitration.py`
- `holo_host/agent_loop_fsm.py`
- `holo_host/agent_event_stream.py`
- `holo_host/reply_api.py`
- `holo_host/stage135_i_state_topology.py`
- `tests/test_stage218_web_research_operator.py`
- `docs/STAGE218_WEB_RESEARCH_OPERATOR.md`
- `docs/ENGINEERING_HANDOFF_STAGE218.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schema

- `holo.stage218.web_research_operator_run.v1`

## Runtime Propagation

- Operator registry exposes `web_research_operator_run`.
- Tool action space includes the registered operator automatically.
- Stage152-derived arbitration maps it to `stage218_web_research_operator_run`.
- Reply runtime dispatches registered operators through `dispatch_operator_action(...)`.
- Capability updates propagate:
  - `stage218_web_research_operator_run`
  - `stage186_live_crawler_search`
  - `stage212_action_journal`
  - `web_observation_ledger`
- FSM checks the Stage218 required observation before finalization.
- Event stream renders `[operator_dispatch]` and `[web_research_operator]`.
- Stage135 topology exposes `web_research_operator` metrics.

## Examples

Ready:

```text
selected_action=web_research_operator_run
stage218_web_research_operator_run.status=ready
canonical_stop_reason=final_answer_ready
final_visible_text starts with "Web research brief:"
```

Network disabled:

```text
stage218_web_research_operator_run.status=rejected
web_observation_ledger[0].status=rejected_network_disabled
canonical_stop_reason=boundary_or_permission
```

Insufficient evidence:

```text
stage218_web_research_operator_run.status=failed|weak
canonical_stop_reason=evidence_exhausted|tool_failure_report
final reports attempted research failure
```

## Constraints Preserved

- Hidden reasoning remains private.
- No provider path was added outside existing processor/operator paths.
- No memory write was introduced.
- No WeChat start or transport authority change.
- Operator is read-only and network-gated.
- Unknown operators remain rejected.

## Test Results

Completed commands:

```powershell
python -m pytest tests\test_stage218_web_research_operator.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage218-green3
python -m pytest tests\test_stage218_web_research_operator.py tests\test_stage217_operator_registry_dispatch.py tests\test_stage216_model_first_market_operator_action.py tests\test_stage186_live_crawler_search.py tests\test_stage212_action_journal.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage218-targeted
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage218-runtime
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results: `8 passed`, `29 passed`, `92 passed`, `1063 passed`, public hygiene passed, and `git diff --check` exited 0 with CRLF normalization warnings only.

## Next Suggested Stage

Stage219 should improve live CLI research behavior: multi-query continuation policy, source diversity targets, and explicit "search not complete yet" event-stream summaries when evidence remains weak.
