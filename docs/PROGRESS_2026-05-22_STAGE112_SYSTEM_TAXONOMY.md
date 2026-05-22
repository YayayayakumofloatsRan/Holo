# Progress 2026-05-22: Stage112 System Taxonomy

## Goal

Manually expand conversation categories into a role-agnostic system taxonomy and
test tool-call ability at the system boundary.

## Implemented

- Added `holo_host.stage112_system_taxonomy`.
- Added `stage112-system-taxonomy` CLI.
- Added 34 system-level, role-agnostic category fixtures.
- Preserved Stage105-110 routing simulation for each category.
- Added role-marker violation checks.
- Added family coverage counts.
- Added a deterministic tool-call probe covering:
  - Stage106 allowlisted tool schema exposure;
  - provider `tool_calls` parsing;
  - accepted `external_lookup`;
  - accepted `memory_recall`;
  - rejected unknown `shell_exec`;
  - Stage107 transition into local tool execution waiting.

## Evidence

RED:

```powershell
python -m pytest -q tests\test_stage112_system_taxonomy.py --basetemp .holo_runtime\pytest-stage112-red
```

Observed:

- `ModuleNotFoundError: No module named 'holo_host.stage112_system_taxonomy'`

GREEN:

```powershell
python -m pytest -q tests\test_stage112_system_taxonomy.py --basetemp .holo_runtime\pytest-stage112-green
```

Observed:

- `4 passed`

## Boundary

This stage tests local provider-tool adaptation and loop handling. It does not
spend live DeepSeek API calls. Live provider batch testing can reuse the same
taxonomy in a later stage.
