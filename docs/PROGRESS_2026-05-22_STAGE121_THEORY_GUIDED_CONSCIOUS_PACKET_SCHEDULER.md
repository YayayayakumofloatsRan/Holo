# Progress: Stage121 Theory-Guided Conscious Packet Scheduler

Date: 2026-05-22

## Goal

Begin building theory-guided continuous thought flow by making provider packet
size, cache-prefix strategy, output budget, and tool-loop depth dynamic.

## Rationale

Long packets can better exploit a strong provider model, but long packets only
help when they are structured. Stage121 therefore treats the packet as a
cache-aware working-memory surface:

- stable reusable prefix first;
- selected memory and attractors in the middle;
- volatile user turn and tool observations last;
- enough output room and tool-loop room for continuous thought.

## Completed

- Added `holo_host/stage121_conscious_packet_scheduler.py`.
- Added dynamic packet policy fields:
  - `target_input_tokens`
  - `expansion_budget_tokens`
  - `output_budget_tokens`
  - cache prefix target and digest
  - stream mode and phases
  - dynamic max tool rounds/calls
- Wired `CodexCliProcessor.generate` to apply Stage121 policy to live provider
  metadata and output budget.
- Preserved DeepSeek cache usage counters:
  - `prompt_cache_hit_tokens`
  - `prompt_cache_miss_tokens`
- Added CLI inspection:

```text
python -m holo_host stage121-packet-policy --query "构建理论指导下的连续意识流，尽可能长包并考虑缓存" --prompt-repeat 80 --uncertainty 0.8 --tool memory_recall --tool test_runner
```

The smoke selected `continuous_thought`, target input `45353` tokens,
expansion budget `44854` tokens, output budget `2200` tokens, and tool-loop
budget `6` rounds / `24` tool calls.

- Did not touch live WeChat or watcher transport.

## Verification

```text
python -m pytest -q tests/test_stage121_conscious_packet_scheduler.py --basetemp=.pytest_tmp_stage121
4 passed in 0.23s
```

```text
python -m pytest -q tests/test_stage120_tool_affordance_optimizer.py tests/test_stage121_conscious_packet_scheduler.py tests/test_stage118_tool_expansion.py tests/test_stage119_tool_library_expansion.py --basetemp=.pytest_tmp_stage121_regression
19 passed in 8.76s
```

```text
python -m pytest -q --basetemp=.pytest_tmp_full_stage121
406 passed in 74.18s (0:01:14)
```

## Next

The next cut should make packet expansion concrete: use the Stage121
`expansion_budget_tokens` to pull additional selected memory, attractor
summaries, and tool observations into the packet until the target input budget
is approached.
