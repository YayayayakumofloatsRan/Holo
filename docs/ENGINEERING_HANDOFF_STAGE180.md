# Engineering Handoff Stage180

## Summary

Stage180 adds a live remediation executor. It consumes Stage179 `next_action_candidates`, executes the subset backed by existing safe host surfaces, records the resulting observation ledgers, and reruns the FSM so execution can change the stop state.

This is the first step where the generic evidence/action remediation arc performs real host-side action instead of only producing a plan.

## Files Changed

```text
holo_host/live_remediation_executor.py
holo_host/agent_loop_fsm.py
holo_host/agent_event_stream.py
holo_host/cli.py
holo_host/reply_api.py
holo_host/stage135_i_state_topology.py
tests/test_stage180_live_remediation_executor.py
docs/STAGE180_LIVE_REMEDIATION_EXECUTOR.md
docs/ENGINEERING_HANDOFF_STAGE180.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage180.live_remediation_executor.v1
holo.stage180.live_remediation_execution_simulation.v1
```

## CLI

```powershell
python -m holo_host run-live-remediation-execution --output artifacts\stage180\stage180_live_remediation_execution.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Behaviors

```text
primary_literature_search + web_search -> web_observation_ledger
inspect_experiment_artifacts + file_read -> engineering_action_ledger
run_memory_recall + memory_recall -> memory_observation_ledger
execution success -> remediation_execute FSM step
execution success -> [remediation_exec] event stream
execution success -> Stage135 live_remediation_executor node
```

Stage180 uses network gating and existing workspace/path safety. It rejects unsupported or under-specified remediation actions instead of inventing execution.

## Verification

Initial TDD red:

```powershell
python -m pytest tests\test_stage180_live_remediation_executor.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage180-red
```

Result: failed because `holo_host.live_remediation_executor`, FSM execution metadata, CLI command, event rendering, and topology node did not exist.

Targeted green:

```powershell
python -m pytest tests\test_stage180_live_remediation_executor.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage180-green3
```

Result: `9 passed in 4.70s`.

Final targeted stack:

```powershell
python -m pytest tests\test_stage180_live_remediation_executor.py tests\test_stage179_live_remediation_loop.py tests\test_stage178_evidence_action_remediation.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage180-targeted-fix
```

Result: `25 passed in 5.15s`.

Simulation:

```powershell
python -m holo_host run-live-remediation-execution --output artifacts\stage180\stage180_live_remediation_execution.html --dry-run
```

Result: `status=passed`, `case_count=5`, `executed_case_count=2`, artifacts written to `artifacts\stage180\stage180_live_remediation_execution.{html,json,jsonl}`.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage180-runtime-fix
```

Result: `92 passed in 9.12s`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `878 passed in 95.91s`.

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result: hygiene passed; `git diff --check` passed with only CRLF worktree warnings.

## Constraints Preserved

- no provider model call added
- no network fetch without `network_enabled`
- no arbitrary shell execution
- no write-action execution
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure

## Next Suggested Stage

Stage181 should stress-test the full remediation execution loop against adversarial live-agent scenarios: failed search retries, stale evidence, partial observations, missing artifact paths, and multi-action continuation budgets.
