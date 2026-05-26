# Engineering Handoff Stage151

Date: 2026-05-26

## Summary

Stage151 now implements a Codex-style host tool decision loop for web/time evidence. Holo builds time observations every turn, scores action candidates, executes selected `web_search`, `open_page`, or `find_in_page` actions when network is enabled, records normalized web observations, and renders an auditable CLI trace.

The immediate production fix is that Holo should no longer visibly claim "I searched", "latest", "official", or equivalent current-web facts unless `web_observation_ledger` contains a successful source-backed observation. When evidence is missing, the visible answer is repaired before delivery/archive.

## Files Changed

- `holo_host/stage151_tool_decision_loop.py`
- `holo_host/capabilities.py`
- `holo_host/reply_api.py`
- `holo_host/cli.py`
- `holo_host/tool_grounding.py`
- `holo_host/stage150_context_memory_fabric.py`
- `holo_host/stage135_i_state_topology.py`
- `holo_host/stage151_live_tool_trace.py`
- `tests/test_stage151_tool_decision_loop.py`
- `tests/test_stage151_live_tool_trace.py`
- `tests/test_capabilities.py`
- `docs/STAGE151_TOOL_DECISION_LIVE_TRACE.md`
- `docs/ENGINEERING_HANDOFF_STAGE151.md`
- `docs/ROADMAP_REGISTRY.md`
- `HOLO_HANDOFF.md`

`tests/test_memory_admin.py` was already dirty before Stage151 and was not part of this stage.

## New Schemas

```text
holo.stage151.tool_decision.v1
holo.stage151.live_trace.v1
holo.web_observation.v1
holo.time_observation.v1
```

## Runtime Propagation

Stage151 metadata is propagated through:

- `capability_context`
- Stage150 working context packet
- `ReplyPlan.debug`
- reply JSON/result metadata
- outgoing/archive observe metadata
- Stage135 topology metrics
- CLI `--trace`

Key result fields include:

```text
time_observation
stage151_tool_decision
web_observation_ledger
stage151_tool_decision_grounding
stage151_tool_decision_grounding_status
stage151_live_trace
stage151_web_observation_count
```

## Examples

Grounded web claim:

```text
User: 联网搜索 OpenAI Codex 文档
Trace: web_search status=ok, source_urls present
Final: may cite the observed source.
```

Rejected network:

```text
User: search latest Holo agent paper
Network: disabled
Observation: rejected_network_disabled
Final: must not claim a current lookup succeeded.
```

Workspace tool claim:

```text
Provider: I checked the project directory.
Stage151: does not treat "docs" alone as a web claim.
Stage139: repairs the workspace tool claim unless a workspace/tool observation exists.
```

## Test Results

Verified so far:

```text
python -m pytest tests\test_stage151_tool_decision_loop.py tests\test_stage151_live_tool_trace.py tests\test_tool_grounding.py tests\test_stage150_context_memory_fabric.py tests\test_capabilities.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage151-targeted3
29 passed in 4.62s

python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage151-runtime2
91 passed in 32.76s

python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
588 passed in 99.32s

python scripts\check_public_release_hygiene.py
Public release hygiene passed

git diff --check
passed
```

Live CLI smoke, commit, and push are completed after this handoff is updated by the final verification pass.

## Constraints Preserved

- No WeChat start.
- No memory writes.
- No approval/sandbox implementation.
- No provider call path outside processor fabric.
- No watcher or transport authority widening.
- No hidden chain-of-thought in trace output.

## Next Suggested Stage

Stage152 should make the tool loop multi-step and stopping-aware: after a weak or empty observation, Holo should decide whether to refine query, open a source page, ask clarification, or stop with an honest limitation. That would move from single-pass observation to bounded ReAct-style search.
