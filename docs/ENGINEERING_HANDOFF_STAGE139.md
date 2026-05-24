# Engineering Handoff Stage139

Date: 2026-05-24

## Summary

Stage139 completes the current tool-calling maturation pass. The main behavior change is that Holo now treats local tool observations as first-class state evidence. Tool execution reports are normalized, attached to provider metadata, exposed in reply JSON and memory metadata, rendered into Stage135 topology, and used to repair visible claims that are not backed by an actual observation.

## Changed Files

- `holo_host/tool_grounding.py`
  - Normalizes tool observations.
  - Evaluates visible speech against observation families.
  - Repairs ungrounded tool claims.

- `holo_host/tool_need.py`
  - Classifies deterministic tool need before provider packet construction.
  - Covers workspace, memory, docs, git, tests, external lookup, runtime, artifacts, time, and mutation permission.

- `holo_host/tool_benchmark.py`
  - Adds a deterministic Stage139 benchmark suite.

- `holo_host/codex_runner.py`
  - Adds `tool_observation_ledger`.
  - Adds `tool_failure_reentry`.
  - Keeps rejected tools in the reentry path.

- `holo_host/processors.py`
  - Feeds tool-need classification into Stage120 selection.
  - Propagates tool ledger metadata into `ReplyPlan.debug`.

- `holo_host/reply_api.py`
  - Evaluates final reply grounding before delivery/archive.
  - Adds `tool_observation_ledger` and `tool_grounding` to result and memory metadata.

- `holo_host/stage120_tool_affordance_optimizer.py`
  - Prioritizes explicit non-library requests, granted tools, baseline tools, and topic tools before trimming.

- `holo_host/stage135_i_state_topology.py`
  - Adds actual `tool_observation_*` nodes from the ledger.

- `holo_host/cli.py`
  - Adds `stage139-tool-benchmark`.

## New Tests

- `tests/test_tool_grounding.py`
- `tests/test_tool_need.py`
- `tests/test_tool_benchmark.py`

Updated tests cover:

- DeepSeek tool loop ledger metadata.
- Rejected tool reentry.
- Reply repair for ungrounded workspace claims.
- Stage135 topology observation nodes.
- Stage120 topic-aware bounded tool selection.
- Stage139 benchmark CLI.

## Commands

Run the deterministic tool benchmark:

```bash
python3 -m holo_host stage139-tool-benchmark
```

Run the tool-chain regression:

```bash
python -m pytest tests/test_stage106_deepseek_tool_adapter.py tests/test_stage113_agent_tool_executor.py tests/test_stage114_agent_tool_cycle.py tests/test_stage115_deepseek_agent_tool_loop.py tests/test_stage116_multiround_agent_tools.py tests/test_stage117_complete_agent_tooling.py tests/test_stage118_tool_expansion.py tests/test_stage119_tool_library_expansion.py tests/test_stage120_tool_affordance_optimizer.py tests/test_stage123_internal_tool_flow.py -q
```

Run the full suite on Windows with an explicit temp root:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

## Verified Results

- `13 passed in 0.97s`
- `42 passed in 9.22s`
- `479 passed in 86.76s`
- `python -m holo_host stage139-tool-benchmark` reports `tool_precision=1.0`, `tool_recall=1.0`, `ungrounded_claim_count=1`

## Notes For Next Work

The next practical optimization should be memory answer grounding. The pattern is now available from tool grounding: a final answer should carry source family, selected memory ids, confidence, missing-source status, and a visible fallback when the source is unavailable.

After memory grounding, implement A' to A'' novelty checks so the progressive reply stream stops repeating itself and becomes a real state update sequence.
