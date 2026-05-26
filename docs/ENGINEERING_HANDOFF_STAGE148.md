# Engineering Handoff Stage148

Date: 2026-05-26

## Summary

Stage148 adds a deterministic ReAct substrate and reusable state-memory packet to the reply path. Holo now separates raw recent dialogue events from memory-like state slots and exposes a compact `perceive -> plan -> act -> observe` report for each reply turn.

The implementation focuses on the user-observed failure where Holo could not reliably carry immediate corrections or recent context into the next turn. This stage does not solve all agent planning, but it gives the provider a structured state/action packet instead of relying on vague transcript recall.

## Files Changed

- Added `holo_host/stage148_react_agent_loop.py`
- Added `tests/test_stage148_react_agent_loop.py`
- Added `docs/STAGE148_REUSABLE_STATE_MEMORY_AGENT_LOOP.md`
- Added `docs/ENGINEERING_HANDOFF_STAGE148.md`
- Modified `holo_host/reply_api.py`
- Modified `holo_host/processors.py`
- Modified `holo_host/stage135_i_state_topology.py`
- Modified `HOLO_HANDOFF.md`
- Modified `docs/ROADMAP_REGISTRY.md`

## New Schema

```text
holo.stage148.reusable_state_react_loop.v1
```

## Runtime Propagation

`reply_api.py` builds `stage148_react_state` before processor generation and inserts it into the sidecar. `processors.render_chat_prompt()` renders it as `Reusable State Memory` and `ReAct State`.

After the reply is grounded and packet reports are computed, `reply_api.py` rebuilds Stage148 with the observed tool/memory/packet/context/reaction evidence and propagates:

- `stage148_react_state`
- `stage148_react_plan_action`

into final reply JSON, outgoing metadata, and archive/observe metadata.

Stage135 topology now shows a `react_loop` node with event count, reusable slot count, and selected plan action.

## Examples

User correction:

```text
我跟你反复说过了，不要用emoji
```

Stage148 state slot:

```text
slot_type=recent_correction
summary=avoid frequent emoji and emoticons; user correction should persist across channels
```

Prior-context query:

```text
三句以前，我说了什么？
```

Stage148 ReAct plan:

```text
selected_action_hint=memory_recall
required_observations=["recent_event_log", "working_state_slots"]
```

Generic continuation:

```text
继续
```

Stage148 keeps recent event and unresolved-question slots available so the provider can continue against the current task state.

## Constraints Preserved

- No provider calls added
- No durable memory writes added
- No tool execution added
- No WeChat start
- No transport authority widening
- No second brain loop
- No hidden chain-of-thought exposure

## Test Results

Executed:

```powershell
python -m pytest tests\test_stage148_react_agent_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage148-targeted
```

Result:

```text
7 passed in 0.43s
```

Executed:

```powershell
python -m pytest tests\test_stage148_react_agent_loop.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage148-targeted
```

Result:

```text
19 passed in 1.16s
```

## Next Suggested Stage

Stage149 should mature the action side of the loop:

```text
Stage149 Action Outcome Observation And Tool-First Planner
```

It should make the planner choose between direct answer, memory recall, tool-first, clarification, and defer using current observations, then record action outcomes back into reusable state.
