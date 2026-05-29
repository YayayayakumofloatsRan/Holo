# Engineering Handoff Stage249

## Summary

Stage249 is a foundation review for `kernel_v3` Phase0 through Phase3. The goal was not to add a new operator surface; it was to inspect the kernel base for clarity, phase layering, host-owned control, and reproducible context behavior before later retrieval, citation, planner, and operator work builds on it.

The review found one concrete Phase3 consistency defect: `ContextPackCompiler` used the latest three observation ledger records for `recent_observations`, while `MemoryRead.query_observations()` and `MemoryRead.query_citations()` returned the first three matching records by default. That could place different evidence windows in the same ContextPack. Stage249 fixes this by adding an explicit recent-read order and making the compiler use the same latest-window semantics for observations, memory refs, and citations.

## Files Changed

- `kernel_v3/context/compiler.py`
- `kernel_v3/context/memory_read.py`
- `tests/test_kernel_v3_phase3_context_compiler.py`
- `tests/test_kernel_v3_phase3_memory_read.py`
- `docs/ENGINEERING_HANDOFF_STAGE249.md`

## Phase Layering Reviewed

Phase0 contracts:

- `kernel_v3/contracts.py` remains the schema boundary.
- The kernel still serializes state through typed dataclass contracts.
- No old `holo_host` modules are imported by `kernel_v3`.

Phase1 durable loop:

- `LoopControllerV3` remains thin.
- The loop records context, action, policy decision, observation, feedback, and result into the journal.
- Direct answers still go through the same loop path as tool actions.
- Resume remains task-id based through `SessionEngine` and journal replay.

Phase2 permissioned tool plane:

- Tools are reached through `ToolRegistry` and `ToolManifest`.
- `PolicyGate` validates side effects and permissions before tool execution.
- Network is represented as a disabled contract-only tool; no live fetch was introduced.
- `LoopControllerV3` does not dispatch by concrete tool names.

Phase3 context and memory read path:

- `ContextPackCompiler` reads from journal records, task state, artifact refs, memory refs, project profile, tool briefs, and permission state.
- `MemoryRead` exposes read-only queries for historical observations, artifacts, and citation refs.
- Context sections are bounded, redacted, and deterministically hashed.
- CLI context inspection supports dump, section list, and artifact references.

## Stage249 Fix

Before Stage249, these three ContextPack sections could refer to inconsistent ledger windows when a task had more than three observations:

- `recent_observations`: latest three observations
- `memory_refs`: first three observations
- `citations`: first three observations

The fix adds `order="recent"` to `MemoryRead.query_observations()` and `MemoryRead.query_citations()`. The recent order returns the latest `limit` matches while preserving journal order inside the returned window. `ContextPackCompiler` now uses that mode, so `recent_observations`, `memory_refs`, and `citations` are derived from the same evidence window.

The same review also clarified the query boundary for `limit <= 0`: observation, citation, and artifact read queries now return an empty list. This prevents accidental non-empty reads when a caller intentionally requests a zero-sized context or inspection window.

## Invariants Preserved

- The model proposes; the host validates, executes, records, and verifies.
- Journal remains the source of truth.
- Memory remains derived from journal observations and artifact references.
- No long-term memory write path was introduced.
- No live web retrieval was introduced.
- No live model or provider call was introduced.
- No subagent path was introduced.
- No WeChat transport or decision authority was introduced.
- `LoopControllerV3` remains tool-name agnostic.
- Policy-blocked actions remain normal journaled outcomes, not exceptional control flow.

## Review Notes

The main code-quality criterion was internal consistency across phase boundaries:

- Phase0 schemas should not know runtime provider details.
- Phase1 loop should not know concrete tool names.
- Phase2 tools should not execute without policy context.
- Phase3 context should not mix observation, memory, and citation windows.

The Stage249 code change is deliberately narrow because the broader Phase0-3 architecture already has targeted tests for direct answer flow, generic dispatch, policy blocking, feedback continuation, resume, journal references, permissioned tools, redaction, deterministic hashing, and CLI context inspection.

## Verification

Stage249 targeted verification:

```powershell
pytest -q tests/test_kernel_v3_phase3_memory_read.py tests/test_kernel_v3_phase3_context_compiler.py
```

Expected result after Stage249:

```text
10 passed
```

Full kernel v3 verification to run before publishing:

```powershell
pytest -q tests -k kernel_v3
python -m compileall -q kernel_v3
rg -n "holo_host|reply_api|processors|memory_bridge|pyweixin|wechat|WeChat|requests|urllib|httpx|openai|anthropic|deepseek|DEEPSEEK_API_KEY|OPENAI_API_KEY" kernel_v3
rg -n "workspace\.search|file\.read|web_search|page_open|memory_consolidate|subagent|research|wechat|DeepSeek|deepseek" kernel_v3\loop.py
git diff --check -- kernel_v3 tests/test_kernel_v3*.py docs/ENGINEERING_HANDOFF_STAGE249.md holo-v3
```

The dependency scans are expected to return no matches. `git diff --check` may print CRLF normalization warnings on Windows; those are not whitespace errors.

## Release Boundary

This stage publishes only the `kernel_v3` foundation review and its tests/documentation. Existing dirty old-system files under `holo_host/` and non-kernel tests are intentionally outside this commit unless a later stage explicitly scopes them in.

## Next Suggested Stage

Stage250 should start only after this foundation remains green. The next useful work is a Retrieval FSM / EvidenceItem / Citation operator layer that consumes the standardized Phase3 ContextPack without adding live retrieval, provider calls, or transport authority inside `kernel_v3`.
