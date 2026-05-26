# Engineering Handoff Stage154

## Summary

Stage154 adds a workspace-scoped engineering action fabric. Holo can now record repo search, file read, patch, test, git status, and git diff actions as auditable ledgers, render them in the interactive CLI, and reject unsupported visible engineering claims.

## Files Changed

- `holo_host/engineering_workspace_tools.py`
- `holo_host/engineering_action_fabric.py`
- `holo_host/agent_event_stream.py`
- `holo_host/interactive_cli.py`
- `holo_host/cli.py`
- `holo_host/reply_api.py`
- `holo_host/processors.py`
- `holo_host/stage150_context_memory_fabric.py`
- `holo_host/stage135_i_state_topology.py`
- `tests/test_stage154_engineering_action_fabric.py`
- `docs/STAGE154_ENGINEERING_ACTION_FABRIC.md`
- `docs/ENGINEERING_HANDOFF_STAGE154.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schemas

```text
holo.stage154.engineering_action.v1
holo.stage154.engineering_verification_ledger.v1
```

## Runtime Propagation

- `engineering_workspace_tools.py` implements workspace-scoped `workspace_search`, `file_read`, `apply_patch`, `test_run`, `git_status`, and `git_diff`.
- `engineering_action_fabric.py` normalizes action ledgers, converts them into tool-style evidence, and verifies visible engineering claims.
- `reply_api.py` merges Stage154 ledgers from metadata/sidecar/debug, repairs unsupported read/patch/test/diff claims, and propagates Stage154 metadata into reply JSON, outgoing metadata, archive metadata, and debug.
- `processors.py` passes Stage154 metadata through provider result metadata and Stage135 topology.
- `stage150_context_memory_fabric.py` includes engineering observations in the evidence ledger view.
- `agent_event_stream.py` renders `[eng:search]`, `[eng:read]`, `[eng:patch]`, `[eng:test]`, `[eng:diff]`, and `[eng:handoff]`.
- `cli.py` adds `/eng ...` commands for local engineering action execution without starting WeChat.
- `stage135_i_state_topology.py` exposes an `engineering_action_fabric` node and counters.

## Examples

Grounded read claim:

```text
Claim: I read README.md.
Evidence: file_read status=ok files_read=["README.md"]
Result: grounded
```

Unsupported patch/test claim:

```text
Claim: I patched it and tests passed.
Evidence: no apply_patch or test_run ledger
Result: unverified_engineering_claim, visible reply repaired
```

Rejected dangerous command:

```text
/eng test git reset --hard
status=rejected
stderr_summary=Stage154 dangerous command policy
```

## Constraints Preserved

- No WeChat start.
- No transport authority widening.
- No provider call path added.
- No durable memory writes added.
- No approval/sandbox UI added.
- Destructive commands remain rejected by default.
- Provider-visible statements are not treated as engineering proof; only host ledgers are proof.

## Verification

Targeted:

```text
python -m pytest tests\test_stage154_engineering_action_fabric.py tests\test_stage153_interactive_cli.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage154-targeted
18 passed in 1.51s
```

Runtime:

```text
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage154-runtime
91 passed in 11.67s
```

Full:

```text
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
616 passed in 74.10s (0:01:14)
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

Stage155 should connect Stage154 with the DeepSeek native tool loop: expose engineering tools as provider-callable host tools under the same ledger and rejection policy, while keeping raw reasoning hidden and destructive actions blocked.
