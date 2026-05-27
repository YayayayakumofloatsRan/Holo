# Engineering Handoff Stage160R

Date: 2026-05-27

## Summary

Stage160R depersonalizes the agent kernel for `holo_cli` and related engineering/research/project channels, adds a first-class intent frame, introduces per-thread goal continuity, and enforces a host-owned finite-state loop over mandatory tool decisions.

This stage directly addresses the live CLI failure modes:

- memory recall candidates now require execution or an explicit missing/unavailable observation;
- follow-up turns such as `还有呢？` inherit the previous memory goal;
- bare `?` after a failed answer enters follow-up/repair instead of social speculation;
- failed web lookup reports attempted failure rather than claiming a future search;
- new turns do not report `[stop] unknown`;
- `holo_cli` prompts strip WeChat/persona/playful companion language.

## Files Changed

Added:

```text
holo_host/agent_loop_fsm.py
holo_host/agent_kernel_prompt_policy.py
holo_host/agent_intent_frame.py
holo_host/agent_goal_state.py
tests/test_stage160r_depersonalized_agent_loop.py
docs/STAGE160R_DEPERSONALIZED_AGENT_LOOP_FSM.md
docs/ENGINEERING_HANDOFF_STAGE160R.md
```

Modified:

```text
holo_host/agent_event_stream.py
holo_host/context_compiler.py
holo_host/processors.py
holo_host/reply_api.py
holo_host/stage135_i_state_topology.py
holo_host/stage150_context_memory_fabric.py
holo_host/stage151_tool_decision_loop.py
HOLO_HANDOFF.md
docs/ROADMAP_REGISTRY.md
```

## Runtime Propagation

Stage160R metadata is propagated through:

```text
ReplyPlan.debug
reply JSON
outgoing metadata
archive/observe metadata
Stage150 working context packet
Stage156 context compiler observations
Stage153 event stream
Stage135 topology
active_thread_state metadata
```

Public metadata includes:

```text
stage160r_intent_frame
stage160r_agent_loop_fsm
stage160r_goal_state
```

## Examples

Grounded/missing memory recall:

```text
User: 回忆一下上次和你的对话
FSM: mandatory_actions=[memory_recall]
If no source: evidence_exhausted + explicit memory_recall failure report
```

Follow-up inheritance:

```text
User: 还有呢？
FSM: intent_type=followup; inherited_from_goal_id=<previous memory goal>
```

Web failure:

```text
User: 联网搜索 OpenAI Codex 官方文档
FSM: mandatory_actions=[web_search]
If provider/network fails: tool_failure_report; final says web_search was attempted and failed
```

## Verification

Executed:

```text
python -m pytest tests\test_stage160r_depersonalized_agent_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage160r-targeted
16 passed

python -m pytest tests\test_stage151_tool_decision_loop.py tests\test_stage152_deepseek_tool_loop.py tests\test_stage153_interactive_cli.py tests\test_stage159_kernel_hardening.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage160r-neighbor
43 passed

python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage160r-runtime
91 passed
```

```text
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
688 passed

python scripts\check_public_release_hygiene.py
Public release hygiene passed

git diff --check
passed with CRLF normalization warnings only
```

## Constraints Preserved

- No provider call path added.
- No self-memory write added by Stage160R.
- No WeChat start.
- No transport authority widening.
- No domain module implementation.
- No hidden DeepSeek reasoning exposure.
- Stage151/152/153/159 grounding and hardening regressions remain passing.

## Next Suggested Stage

Stage161 should make host-owned memory recall more semantically useful: reusable state slots, short-term conversation indexing, and retrieval quality diagnostics should feed the Stage160R FSM as first-class observations rather than plain transcript snippets.
