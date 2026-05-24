# Engineering Handoff Stage140

Date: 2026-05-24

## Summary

Stage140 implements memory answer grounding. Holo now normalizes memory observations, scans visible speech for memory claims, repairs unsupported recall language, propagates memory grounding metadata into reply JSON and archive metadata, and renders actual memory observation nodes in Stage135 topology.

## Changed Files

- `holo_host/memory_grounding.py`
  - Adds `holo.memory_grounding.v1`.
  - Normalizes memory observations from sidecar, recall reconstruction, vector hits, active history refresh, and memory tool observations.
  - Detects English and Chinese visible memory claim families.
  - Repairs ungrounded, weak, or contradicted memory claims.

- `holo_host/processors.py`
  - Adds `memory_observation_ledger` to `ReplyPlan.debug`.
  - Passes memory observations into Stage135 topology on fast-only and deep paths.

- `holo_host/reply_api.py`
  - Runs final memory grounding before bubble finalization.
  - Adds `memory_observation_ledger` and `memory_grounding` to outgoing metadata, archive/observe metadata, and reply JSON.
  - Delegates memory-only tool grounding misses to Stage140.

- `holo_host/stage135_i_state_topology.py`
  - Adds `memory_observation_*` topology nodes.
  - Adds `memory_observation_node_count`.

- `tests/test_memory_grounding.py`
  - Covers missing-source memory queries, selected memory ids, ungrounded claims, weak memory sources, and memory tool observations.

- `tests/test_stage135_i_state_topology.py`
  - Covers actual memory observation nodes and processor debug propagation.

- `tests/test_holo_host.py`
  - Covers reply API repair and archive metadata propagation for ungrounded memory claims.

## Verification

Already run:

```powershell
python -m pytest tests\test_memory_grounding.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage140-memory
python -m pytest tests\test_tool_grounding.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage140-tool
python -m pytest tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage140-stage135
python -m pytest tests\test_holo_host.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage140-holo-host
python -m pytest tests\test_memory_grounding.py tests\test_tool_grounding.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage140-targeted
python -m holo_host reply-probe --query "Stage140 live smoke: do you remember what the memory grounding gate should do? Answer briefly and include grounding metadata if available." --thread-key holo_cli:stage140 --chat-name Stage140Live --channel holo_cli --mode hybrid
```

Observed:

- `5 passed in 0.24s`
- `3 passed in 0.14s`
- `8 passed in 0.44s`
- `74 passed in 27.86s`
- `16 passed in 0.69s`
- Live provider probe returned `retrieval_mode=hybrid-led+fallback`, `graph_confidence=1.0`, and Stage135 topology with `memory_observation_node_count=2`.
- Full regression after implementation: `486 passed in 70.52s`.

## Constraints Preserved

- No self-memory writes were added.
- No provider call path was added outside processor fabric.
- No watcher or transport authority was widened.
- Memory grounding is observability and visible-speech repair only.

## Next Work

The next technical step should be source sufficiency scoring. Stage140 verifies that a memory source exists and has strength, but it does not yet check whether a detailed answer claim is semantically entailed by the selected source. That should become a Stage141 claim-to-memory alignment gate.
