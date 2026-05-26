# Engineering Handoff Stage150

Date: 2026-05-26

## Summary

Stage150 adds a deterministic Codex-style context memory fabric. Holo now builds a structured working-context packet before provider generation and rebuilds it after final grounding and repair metadata are available.

This stage directly addresses the gap between "raw chat history exists" and "the provider receives the right working state." The packet separates user goal, active task, reusable state, directives, evidence, open loops, compact background, and forbidden visible claims.

## Files Changed

- Added `holo_host/stage150_context_memory_fabric.py`
- Added `tests/test_stage150_context_memory_fabric.py`
- Added `docs/STAGE150_CODEX_STYLE_CONTEXT_MEMORY.md`
- Added `docs/ENGINEERING_HANDOFF_STAGE150.md`
- Modified `holo_host/processors.py`
- Modified `holo_host/reply_api.py`
- Modified `holo_host/stage135_i_state_topology.py`
- Modified `tests/test_holo_host.py`
- Modified `tests/test_stage135_i_state_topology.py`
- Modified `HOLO_HANDOFF.md`
- Modified `docs/ROADMAP_REGISTRY.md`

## New Schema

```text
holo.stage150.context_memory_fabric.v1
```

## Runtime Propagation

`reply_api.py` builds `stage150_context_memory_fabric` before processor generation after Stage148 and Stage149 have been built.

`processors.render_chat_prompt()` renders:

```text
Engineering Context State:
```

The prompt block includes:

- User Goal
- Active Task
- Directives
- Working Context
- Evidence Ledger
- Open Loops
- Background Compact Summary
- Forbidden Visible Claims when needed

After visible repair and grounding gates, `reply_api.py` rebuilds Stage150 with final evidence metadata and propagates:

- `stage150_context_memory_fabric`
- `stage150_context_memory_fabric_slot_count`
- `stage150_context_memory_fabric_evidence_count`
- `stage150_context_memory_fabric_open_loop_count`
- `stage150_background_compact_internal`

into reply JSON, outgoing metadata, archive/observe metadata, and `ReplyPlan.debug`.

Stage135 topology exposes a `context_memory_fabric` node and metrics:

- `context_memory_fabric_node_count`
- `context_memory_fabric_slot_count`
- `context_memory_fabric_open_loop_count`
- `context_memory_fabric_evidence_count`

## Instruction Hierarchy

Stage150 resolves:

```text
system_policy
persona_style_memory
project_instruction
domain_instruction
module_instruction
current_task_instruction
user_directive
```

Specific instructions override broad ones. Stage149 user directives outrank persona/style/profile memory.

## Evidence Discipline

Stage150 scans candidate visible text when available and marks read, tool, test, and patch claims as unverified unless matching observation ledgers exist. It does not create proof and does not execute tools.

Example:

```text
I read the files, patched the code, and tests passed.
```

without matching ledgers produces:

```text
unverified_claim_families = ["patch", "read", "test"]
```

and a forbidden visible-claim reminder.

## Constraints Preserved

- No provider calls added
- No tool execution added
- No durable memory writes added
- No approval or sandbox policy implementation
- No WeChat start
- No transport authority widening
- No second loop
- Background compact remains internal and is not visible speech
- Stage149 visible-output repair remains authoritative

## Test Results

Initial TDD red:

```powershell
python -m pytest tests\test_stage150_context_memory_fabric.py tests\test_holo_host.py::ReplyServiceTests::test_reply_service_propagates_stage150_context_memory_fabric_metadata tests\test_stage135_i_state_topology.py::test_stage135_topology_includes_context_memory_fabric_node -q --basetemp D:\Holo\holo\.pytest_tmp\stage150-red
```

Result:

```text
ModuleNotFoundError: No module named 'holo_host.stage150_context_memory_fabric'
```

Targeted green after implementation:

```powershell
python -m pytest tests\test_stage150_context_memory_fabric.py tests\test_holo_host.py::ReplyServiceTests::test_reply_service_propagates_stage150_context_memory_fabric_metadata tests\test_stage135_i_state_topology.py::test_stage135_topology_includes_context_memory_fabric_node -q --basetemp D:\Holo\holo\.pytest_tmp\stage150-green-2
```

Result:

```text
9 passed in 0.41s
```

Broader verification should be appended after final regression.

Executed:

```powershell
python -m pytest tests\test_stage150_context_memory_fabric.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage150-targeted
```

Result:

```text
7 passed in 0.23s
```

Executed:

```powershell
python -m pytest tests\test_stage149_user_directives.py tests\test_stage148_react_agent_loop.py tests\test_stage135_i_state_topology.py tests\test_holo_host.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage150-runtime
```

Result:

```text
108 passed in 17.48s
```

Executed:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result:

```text
571 passed in 78.25s (0:01:18)
```

Executed:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

```text
Public release hygiene passed.
git diff --check exited successfully with CRLF warnings only.
```

## Next Suggested Stage

Stage151 should calibrate live packet quality using the Stage150 structured context packet, especially whether intent, directives, and evidence discipline improve tool selection and memory recall in actual CLI conversations.
