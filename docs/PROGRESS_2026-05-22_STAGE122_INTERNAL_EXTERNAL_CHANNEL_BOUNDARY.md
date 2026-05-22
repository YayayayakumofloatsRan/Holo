# Progress 2026-05-22: Stage122 Internal/External Channel Boundary

## Scope

Stage122 continues the theory-guided continuous thought stream by separating:

- what Holo receives from the outside world
- what Holo locally intends to do next
- what Holo records as summary-only internal processing
- what Holo is allowed to say externally

This is a provider-above adaptation layer. It does not claim subjective
consciousness and does not expose raw hidden reasoning.

## Changes

- Added `holo_host/stage122_internal_external_channel_boundary.py`.
- Added stable provider contract text:
  - `internal_intent`
  - `internal_processing`
  - `external_speech_only`
- Wired `CodexCliProcessor.generate()` to:
  - append the Stage122 channel contract to the actual provider prompt
  - build Stage121 policy after the contract is attached
  - attach `stage122_channel_frame` to provider metadata
  - expose the same frame in reply debug output
- Added read-only CLI:
  - `python -m holo_host stage122-channel-boundary`
- Updated provider compatibility rules.
- Added targeted tests in `tests/test_stage122_channel_boundary.py`.

## Verification

Red test before implementation:

```powershell
python -m pytest -q tests\test_stage122_channel_boundary.py --basetemp=.pytest_tmp_stage122_red
```

Result:

```text
ModuleNotFoundError: No module named 'holo_host.stage122_internal_external_channel_boundary'
```

Targeted test after implementation:

```powershell
python -m pytest -q tests\test_stage122_channel_boundary.py --basetemp=.pytest_tmp_stage122
```

Result:

```text
4 passed in 0.49s
```

## Notes

- No WeChat watcher or live transport was started or modified.
- Stage122 does not execute tools and does not weaken Stage113 permissions.
- The prompt contract is stable for provider-cache friendliness; the detailed
  channel frame remains local metadata.
