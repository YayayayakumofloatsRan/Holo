# Engineering Handoff Stage156

Date: 2026-05-27

## Summary

Stage156 was rebuilt as an actual runtime context compiler. It now converts the Stage150 working-context packet into stable and dynamic prompt sections, records token/cache budget metadata, filters session noise, keeps compact internal, and propagates the report through provider prompt state, reply JSON, outgoing/archive metadata, CLI inspection, and Stage135 topology.

## Files Changed

- `holo_host/context_compiler.py`
- `holo_host/processors.py`
- `holo_host/reply_api.py`
- `holo_host/interactive_cli.py`
- `holo_host/cli.py`
- `holo_host/stage135_i_state_topology.py`
- `tests/test_stage156_context_compiler.py`
- `docs/STAGE156_CONTEXT_COMPILER_CACHE_DISCIPLINE.md`
- `docs/ENGINEERING_HANDOFF_STAGE156.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## Schema

```text
holo.stage156.context_compiler.v1
```

## Runtime Propagation

Stage156 starts from `stage150_context_memory_fabric` and produces:

```text
stable_prefix
project_instruction_block
tool_schema_block
directive_block
dynamic_turn_block
observation_block
final_constraints_block
background_compact
estimated_prompt_tokens
stable_prefix_tokens
dynamic_suffix_tokens
truncated_sections
cache_hit_tokens
cache_miss_tokens
cache_hit_ratio
stable_prefix_cache_key
dynamic_suffix_digest
```

The report is attached to:

```text
TurnContext.mind_packet["stage156_context_compiler"]
ReplyPlan.debug["stage156_context_compiler"]
reply JSON
outgoing metadata
archive/observe metadata
Stage135 topology
interactive CLI /context and /cache views
```

## Prompt Integration

`render_chat_prompt()` now renders:

```text
Engineering Context State:
...

Context Compiler State:
schema=holo.stage156.context_compiler.v1
stable_prefix_tokens=...
dynamic_suffix_tokens=...
current_user_request_exact=...
...
```

`CodexCliProcessor` also includes Stage156 lines in the Stage132 fast context frame, so the fast packet receives the same structured working-context discipline instead of only raw Stage150 summaries.

## Compact Boundary

Background compact is internal only. The compiler records compact summaries for metadata and prompt construction, but visible speech is repaired if it attempts to say "I compacted context." The user-visible wording becomes ordinary working-context wording.

## Test Results

Targeted Stage156:

```powershell
python -m pytest tests\test_stage156_context_compiler.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage156-green-2
```

Result:

```text
11 passed in 0.51s
```

Neighbor regression:

```powershell
python -m pytest tests\test_stage156_context_compiler.py tests\test_stage150_context_memory_fabric.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage156-neighbor-2
```

Result:

```text
32 passed in 1.33s
```

Full verification is recorded in the final Stage156 completion turn.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage156-runtime
```

Result:

```text
91 passed in 22.29s
```

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result:

```text
645 passed in 91.99s (0:01:31)
```

Public hygiene and whitespace:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

```text
Public release hygiene passed: no private profile, memory, runtime, artifact, live transport path, or blocked persona marker is tracked.
git diff --check passed with line-ending warnings only.
```

## Constraints Preserved

- No provider call path was added.
- No tool execution was added.
- No memory write path was added.
- No WeChat start or transport authority widening was added.
- No approval/sandbox policy was implemented.
- Hidden reasoning is not exposed.
- Stage149 directives remain protected from compaction and truncation.

## Next Suggested Stage

Stage157 should evaluate the core agent surfaces against deterministic benchmarks after the corrected Stage156 compiler is in place.
