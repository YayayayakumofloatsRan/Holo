# Progress 2026-05-22: Stage111 Category Simulation

## Goal

Turn manually listed biomimetic conversation categories into a testable packet
simulation suite.

## Implemented

- Added `holo_host.stage111_category_simulation`.
- Added `stage111-category-simulation` CLI.
- Added 14 base category fixtures.
- Added route coverage for:
  - `multi_packet`
  - `single_packet`
  - `tool_first`
  - `stop`
- Added combination candidates for cross-category testing.
- Added self-extension policy and candidate schema for future Holo-driven
  category proposal.
- Fixed Stage105 English hint matching so `research` no longer triggers the
  `search` lookup route.

## Evidence

RED:

```powershell
python -m pytest -q tests\test_stage111_category_simulation.py --basetemp .holo_runtime\pytest-stage111-red
```

Observed:

- `ModuleNotFoundError: No module named 'holo_host.stage111_category_simulation'`

Stage105 regression RED:

```powershell
python -m pytest -q tests\test_stage105_provider_packet_stream.py::test_stage105_research_word_does_not_trigger_search_lookup --basetemp .holo_runtime\pytest-stage105-research-red
```

Observed:

- `tool_request` was incorrectly selected for `research`.

GREEN:

```powershell
python -m pytest -q tests\test_stage111_category_simulation.py --basetemp .holo_runtime\pytest-stage111-green3
```

Observed:

- `4 passed`

Stage105 regression GREEN:

```powershell
python -m pytest -q tests\test_stage105_provider_packet_stream.py::test_stage105_research_word_does_not_trigger_search_lookup tests\test_stage105_provider_packet_stream.py::test_stage105_lookup_query_triggers_tool_even_before_high_uncertainty --basetemp .holo_runtime\pytest-stage105-research-green
```

Observed:

- `2 passed`

## Boundary

Stage111 is still dry-run simulation. It validates packet-routing structure
before provider API spend. The next stage can reuse this category suite for
DeepSeek batch dialogue and response-quality scoring.
