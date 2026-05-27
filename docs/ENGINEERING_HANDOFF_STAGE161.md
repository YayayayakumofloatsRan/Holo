# Engineering Handoff Stage161

Date: 2026-05-27

## Summary

Stage161 implements model-first tool arbitration over a structured action space. Deterministic keyword triage remains only as weak hints and fallback metadata. Runtime now follows the contract: model proposes an action, host validates and executes or rejects it, ledgers prove observations, and the stop controller/final grounding gates close the turn.

## Files Changed

Added:

```text
holo_host/tool_action_space.py
holo_host/model_tool_arbitration.py
holo_host/tool_decision_contract.py
holo_host/agent_loop_policy.py
tests/test_stage161_model_tool_arbitration.py
docs/STAGE161_MODEL_FIRST_TOOL_ARBITRATION.md
docs/ENGINEERING_HANDOFF_STAGE161.md
```

Modified:

```text
holo_host/agent_loop_fsm.py
holo_host/agent_event_stream.py
holo_host/processors.py
holo_host/reply_api.py
holo_host/stage135_i_state_topology.py
HOLO_HANDOFF.md
docs/ROADMAP_REGISTRY.md
```

## Runtime Propagation

Stage161 metadata is propagated through:

```text
ReplyPlan.debug
reply JSON
outgoing metadata
archive/observe metadata
Stage153 event stream
Stage135 topology
active_thread_state metadata
```

Public metadata keys:

```text
stage161_model_tool_arbitration
stage161_tool_decision_validation
stage161_tool_action_space_count
stage161_deterministic_hints
```

## Examples

Memory recall:

```text
Model decision: selected_action=memory_recall
Host result: memory_observation_ledger grounded/weak/missing
If missing: final reports attempted memory recall failure.
```

Web lookup:

```text
Model decision: selected_action=web_search
Host result: web_observation_ledger ok/error/rejected_network_disabled
If failed: final reports the attempted web_search failure.
```

Answer direct:

```text
Model decision: selected_action=answer_direct
Host validation: final claims are checked against web/time, memory, and engineering ledgers.
Unsupported claims are blocked or repaired by existing grounding stages.
```

## Verification

Executed:

```text
python -m pytest tests\test_stage161_model_tool_arbitration.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage161-targeted
16 passed

python -m pytest tests\test_stage160r_depersonalized_agent_loop.py tests\test_stage159_kernel_hardening.py tests\test_stage152_deepseek_tool_loop.py tests\test_stage153_interactive_cli.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage161-neighbor
47 passed

python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage161-runtime
91 passed
```

```text
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
704 passed

python scripts\check_public_release_hygiene.py
Public release hygiene passed

git diff --check
passed with CRLF normalization warnings only
```

## Constraints Preserved

- No runtime provider call path added outside processor fabric.
- No self-memory write added.
- No WeChat start.
- No watcher or transport authority widening.
- No hidden DeepSeek reasoning exposure.
- No persona or WeChat/social prompt contamination in `holo_cli`.
- Stage159 hardening and Stage160R FSM regressions remain passing.

## Next Suggested Stage

Stage162 should improve actual tool execution quality under this model-first arbitration layer: better memory recall result ranking, web retry/search-depth policy, and engineering action execution plans should all feed the same action-space/ledger/FSM contract.
