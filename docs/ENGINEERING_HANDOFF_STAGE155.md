# Engineering Handoff Stage155

## Summary

Stage155 adds a project state graph for durable project continuity. Holo can now store and query typed project nodes for goals, tasks, decisions, open questions, artifacts, sources, assumptions, risks, results, and next actions, with typed edges and evidence. The graph feeds Stage150 structured context and appears in reply/archive metadata and Stage135 topology.

## Files Changed

- `holo_host/project_state_graph.py`
- `holo_host/stage150_context_memory_fabric.py`
- `holo_host/reply_api.py`
- `holo_host/processors.py`
- `holo_host/cli.py`
- `holo_host/stage135_i_state_topology.py`
- `tests/test_stage155_project_state_graph.py`
- `docs/STAGE155_PROJECT_STATE_GRAPH.md`
- `docs/ENGINEERING_HANDOFF_STAGE155.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schema

```text
holo.stage155.project_state_graph.v1
```

## Runtime Propagation

- `project_state_graph.py` owns SQLite-backed graph tables and typed node/edge operations.
- `reply_api.py` loads project state before generation, applies explicit project-state updates after reply construction, and propagates `project_state_graph` plus `project_state_update`.
- `stage150_context_memory_fabric.py` injects active project, active tasks, open questions, latest decisions, next actions, and blocked items into the working context packet and prompt renderer.
- `processors.py` forwards project-state metadata into provider-run metadata and Stage135 topology.
- `cli.py` adds `project-state --summary`, `--open-loops`, and `--next-actions` inspection commands.
- `stage135_i_state_topology.py` exposes a `project_state_graph` node and counters.

## Examples

Detected update:

```text
Task: build project state graph.
Decision: keep it local and deterministic.
Open question: how should visual replay consume it?
Next action: run Stage155 tests.
```

Graph result:

```text
Project -> supports -> Task
Project -> supports -> Decision
Project -> supports -> OpenQuestion
Project -> supports -> NextAction
```

CLI:

```powershell
python -m holo_host project-state --project Holo --summary
python -m holo_host project-state --project Holo --open-loops
python -m holo_host project-state --project Holo --next-actions
```

## Constraints Preserved

- No WeChat start.
- No transport authority widening.
- No provider call path added.
- No tool execution added.
- No self-memory write added.
- No durable policy mutation.
- Explicit project-state cues are required before current-turn text becomes project graph state.

## Verification

Targeted:

```text
python -m pytest tests\test_stage155_project_state_graph.py tests\test_stage150_context_memory_fabric.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage155-targeted
16 passed in 0.76s
```

Runtime:

```text
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage155-runtime
91 passed in 22.02s
```

Full:

```text
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
625 passed in 85.64s (0:01:25)
```

Public hygiene:

```text
python scripts\check_public_release_hygiene.py
Public release hygiene passed: no private profile, memory, runtime, artifact, live transport path, or blocked persona marker is tracked.
```

Diff check:

```text
git diff --check
exit 0; only Git CRLF working-copy warnings were printed.
```

## Next Suggested Stage

Stage156 should connect the project state graph to a bounded planning/review loop: compare current answer, engineering action ledgers, and project graph next actions to detect whether Holo made measurable progress on the active project state.
