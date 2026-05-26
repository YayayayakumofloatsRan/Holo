# Engineering Handoff Stage149

Date: 2026-05-26

## Summary

Stage149 adds a deterministic user-directive kernel. Holo now promotes old and current user corrections, especially "no emoji" and "do not roleplay", into packet-visible hard constraints and final visible-output repair.

This directly targets the observed defect where Holo ignored repeated "不要用 emoji" corrections after a few turns and drifted into roleplay-like language.

Hotfix note: Chinese phrasing such as "请避免使用表情图标" is also treated as a no-emoji hard directive. The prompt now states that user directives override persona, affect style, stock metaphors, and fictional-character imitation.

Semantic-intent note: Stage149 now also consumes Stage124 fast-packet `user_directives`. This makes the first internal provider packet responsible for judging whether the user's message is a durable directive, current-turn constraint, ordinary chat, memory request, or tool/evidence request. Deterministic phrase matching remains a safety net, not the primary long-term strategy.

## Files Changed

- Added `holo_host/stage149_user_directives.py`
- Added `tests/test_stage149_user_directives.py`
- Added `docs/STAGE149_USER_DIRECTIVE_KERNEL.md`
- Added `docs/ENGINEERING_HANDOFF_STAGE149.md`
- Modified `holo_host/reply_api.py`
- Modified `holo_host/processors.py`
- Modified `holo_host/stage135_i_state_topology.py`
- Modified `HOLO_HANDOFF.md`
- Modified `docs/ROADMAP_REGISTRY.md`

## New Schema

```text
holo.stage149.user_directives.v1
```

## Runtime Propagation

`reply_api.py` queries existing thread archive rows through the memory/RAG interface, combines them with recent history and current input, and builds `stage149_user_directives` before processor generation.

`processors.render_chat_prompt()` renders the report into `User Directive State`.

`stage124_fast_deep_thought_loop.py` asks the first fast packet to return `user_directives` and `tool_intent`. `processors.py` merges high-confidence fast-packet directives into `stage149_user_directives` before the deep prompt and final visible repair.

`reply_api.py` applies visible repair after:

- memory repair
- Stage139 tool grounding repair
- Stage140 memory grounding repair
- Stage141 memory-alignment repair
- bubble finalization

The following metadata is propagated into final reply JSON, outgoing metadata, archive/observe metadata, and `ReplyPlan.debug`:

- `stage149_user_directives`
- `stage149_user_directive_status`
- `stage149_user_directive_count`

Stage135 topology shows `user_directive_kernel`.

## Examples

Archived or current user correction:

```text
我跟你反复说过了，不要用emoji
```

Stage149 directive:

```text
directive_type=visible_no_emoji
hard_directive: no emoji or emoticons in visible speech.
```

Current identity correction:

```text
不要再让它role play了
```

Stage149 directive:

```text
directive_type=identity_not_roleplay
hard_directive: do not roleplay; do not explain yourself as a character imitation.
```

Visible repair:

```text
作为虚构角色角色扮演，我记住了 😏
```

becomes a non-emoji, non-roleplay visible reply.

## Constraints Preserved

- No provider calls added
- No durable memory writes added
- No tool execution added
- No WeChat start
- No transport authority widening
- No second brain loop
- No private persona-file mutation
- No direct provider path outside the existing Stage124 processor-fabric fast packet

## Test Results

Executed:

```powershell
python -m pytest tests\test_stage149_user_directives.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage149-targeted
```

Result:

```text
7 passed in 1.07s
```

Executed after the Chinese "避免使用表情图标" hotfix:

```powershell
python -m pytest tests\test_stage149_user_directives.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage149-hotfix
```

Result:

```text
8 passed in 0.64s
```

Additional regression results should be appended after the broader verification run.

Executed:

```powershell
python -m pytest tests\test_stage149_user_directives.py tests\test_stage148_react_agent_loop.py tests\test_stage135_i_state_topology.py tests\test_holo_host.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage149-runtime
```

Result:

```text
103 passed in 51.54s
```

Executed after the hotfix:

```powershell
python -m pytest tests\test_stage149_user_directives.py tests\test_stage148_react_agent_loop.py tests\test_stage135_i_state_topology.py tests\test_holo_host.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage149-hotfix-runtime
```

Result:

```text
104 passed in 33.97s
```

Executed after the semantic fast-packet directive path:

```powershell
python -m pytest tests\test_stage124_fast_deep_thought_loop.py tests\test_stage149_user_directives.py tests\test_stage132_progressive_conscious_stream.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage149-semantic
```

Result:

```text
22 passed in 1.35s
```

Executed:

```powershell
python -m pytest tests\test_stage149_user_directives.py tests\test_stage124_fast_deep_thought_loop.py tests\test_stage148_react_agent_loop.py tests\test_stage135_i_state_topology.py tests\test_holo_host.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage149-semantic-runtime
```

Result:

```text
111 passed in 29.95s
```

Executed:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result:

```text
559 passed in 142.21s (0:02:22)
```

## No-Silence Runtime Hotfix

After live CLI testing, the operator disallowed both visible `[silence: ...]`
output and `silence` as a runtime state. The follow-up hotfix makes low-signal
turns choose `reply_once` with a minimal visible reply, and Stage22 shadow
suppression now reports `returned_action="suppressed"` instead of
`returned_action="silence"`.

Preserved:

- ignore/error diagnostics still print as action fallbacks in CLI.
- defer remains a distinct action.
- Stage22 still suppresses transport delivery in shadow mode, but no longer
  encodes suppression as silence.
- Stage149 user directive handling and Stage124 semantic intent packets are
  unchanged.

Executed:

```powershell
python -m pytest tests\test_cli_chat.py tests\test_holo_host.py -q --basetemp D:\Holo\holo\.pytest_tmp\no-silence-holo-host2
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

```text
85 passed in 18.61s
562 passed in 93.95s (0:01:33)
Public release hygiene passed
git diff --check passed
```

## Next Suggested Stage

Stage150 should use the Stage149 directive kernel as an input to a broader durable preference and state-promotion gate. The goal is to decide which user corrections become long-lived packet constraints, which remain recent working state, and which are only one-turn instructions.
