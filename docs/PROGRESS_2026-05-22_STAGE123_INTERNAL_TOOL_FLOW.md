# Progress 2026-05-22: Stage123 Internal Tool Flow

## Scope

Stage123 makes the continuous internal flow tool-aware. It does not execute
tools directly from hidden state and does not give the provider execution
authority. It turns internal intent into a bounded tool-call opportunity that
still passes through the existing Stage106/113/115/116 chain.

## Changes

- Added `holo_host/stage123_internal_tool_flow.py`.
- Added stable provider prompt contract:
  - use exposed `tool_calls` when internal intent needs memory, evidence,
    lookup, workspace state, or verification
  - provider may propose only
  - Stage113 executes locally in the WSL brain
  - tool observations re-enter before `external_speech`
- Wired `CodexCliProcessor.generate()` to:
  - append the Stage123 prompt contract
  - attach `stage123_internal_tool_flow` to provider metadata
  - expose the same frame in reply debug output
- Added read-only CLI:
  - `python -m holo_host stage123-internal-tool-flow`
- Updated provider compatibility rules.
- Added targeted tests in `tests/test_stage123_internal_tool_flow.py`.

## Verification

Red test before implementation:

```powershell
python -m pytest -q tests\test_stage123_internal_tool_flow.py --basetemp=.pytest_tmp_stage123_red
```

Result:

```text
ModuleNotFoundError: No module named 'holo_host.stage123_internal_tool_flow'
```

Targeted test after implementation:

```powershell
python -m pytest -q tests\test_stage123_internal_tool_flow.py --basetemp=.pytest_tmp_stage123
```

Result:

```text
4 passed in 0.55s
```

Regression:

```powershell
python -m pytest -q tests\test_stage115_deepseek_agent_tool_loop.py tests\test_stage116_multiround_agent_tools.py tests\test_stage117_complete_agent_tooling.py tests\test_stage118_tool_expansion.py tests\test_stage119_tool_library_expansion.py tests\test_stage120_tool_affordance_optimizer.py tests\test_stage121_conscious_packet_scheduler.py tests\test_stage122_channel_boundary.py tests\test_stage123_internal_tool_flow.py --basetemp=.pytest_tmp_stage123_regression
```

Result:

```text
36 passed in 10.28s
```

Full suite:

```powershell
python -m pytest -q --basetemp=.pytest_tmp_full_stage123
```

Result:

```text
414 passed in 74.29s (0:01:14)
```

WSL smoke:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host stage123-internal-tool-flow --query 'internal flow needs memory and workspace tools' --uncertainty 0.8 --tool memory_recall --tool workspace_inspect"
```

Result: returned `stage=123`, `internal_tool_calls.enabled=true`, and
`tool_authority.provider_may_execute_tools=false`.

## Notes

- No WeChat watcher or live transport was started or modified.
- Stage123 preserves the Stage113 permission boundary.
- Stage123 is a control-plane addition: it tells the internal flow when and how
  tool use belongs before external expression.
