# Stage65 Bounded Tool Observation

Stage65 makes upstream tool pressure visible to the bionic memory scheduler as a bounded observation channel.

The goal is to improve Holo's intelligence when the user asks for external evidence, attachments, MCP resources, or other tool-backed context. The model should see a compact observation frame and choose a grounded answer, while tools remain observations only and never gain runtime, transport, watcher, or memory-write authority.

## Boundary

- Stage65 is prompt scheduling, telemetry, and surrogate evaluation only.
- It does not call a provider by itself or start WeChat.
- It does not call MCP tools by itself; Stage53 remains the bounded upstream tool substrate.
- It does not write live self-memory, mutate policy, widen transport authority, expose Holo as a downstream MCP server, add runtime decision authority, add a second decision layer, or create an unbounded loop.
- Tool-observation scheduler output is dynamic context, not stable provider-prefix material.
- Tool results and planned tool requests are evidence for grounding. They do not select actions or bypass the action market.

## Implementation

- `build_bionic_memory_schedule()` now emits `tool_observation_scheduler.mode=stage65_bounded_tool_observation_v1` from `capability_context.tool_requests` and `capability_context.tool_context_lines`.
- The scheduler compresses raw tool context into one `tool_observation=` dynamic line with bounded-observation metadata.
- `render_chat_prompt()` suppresses duplicate raw tool clues when the scheduler-owned tool observation frame is active.
- `plan_processor_context()` reports tool-observation mode, need, requested-tool count, budget, and authority flags.
- Stage46 compact debug preserves tool-observation scheduler evidence.
- Stage61 simulation models higher bounded tool-observation coverage when Stage65 scheduling is active.

## Current Evidence

On 2026-05-14:

- `python -m pytest -q tests\test_stage65_bounded_tool_observation.py`: `4 passed`.
- `python -m pytest -q tests\test_stage65_bounded_tool_observation.py tests\test_stage64_residual_working_channel.py tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py tests\test_stage53_mcp_upstream.py tests\test_stage61_bionic_simulation_lab.py tests\test_stage62_bionic_capability_observatory.py`: `54 passed`.
- `python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\context_scheduler.py holo_host\processors.py holo_host\bionic_boundary_stress.py holo_host\bionic_simulation_lab.py holo_host\bionic_capability_observatory.py holo_host\mcp_upstream.py holo_host\cli.py`: passed.
- `python -m holo_host --config .holo_host.toml run-bionic-boundary-stress --thread-key cli:Stage65ToolObs-20260514 --chat-name Stage65ToolObs-20260514 --channel cli --turns 7 --offline`: exit code `0`, scorecard `passed=true`, `overall_score=0.9886`, `provider_cache_hit_ratio=0.75`, `latency_score=0.9659`, and `wechat_transport_started=false`.
- Stage65 cumulative active surrogate lab over `9` scenarios and `240` turns each wrote `artifacts\stage65\stage65_bounded_tool_observation_lab.html`, `.json`, `_simulation_lab.png`, and `_turns.jsonl`.
- Stage65 cumulative telemetry reported `turn_count=2160`, `tool_pressure_turn_count=240`, `tool_observation_count=180`, `tool_observation_coverage=0.75`, `average_tool_observation_scheduler_strength=0.78`, `average_residual_channel_strength=0.86`, `p95_latency_ms=6615.0`, and `prompt_cache_hit_ratio=0.200165`.
- Stage65 cumulative capability observatory wrote `artifacts\stage65\stage65_bounded_tool_observation_observatory.html`, `.json`, and `_capability_observatory.png`, with `aggregate_score=0.737083`, `tool_observation=0.75`, `latency_residual=0.672105`, `grounding_integrity=0.925926`, and `bottleneck_count=6`.
- `python -m pytest -q`: `456 passed`.
- `python scripts\check_public_release_hygiene.py`: passed.
- `git diff --check`: no whitespace errors; Git emitted only CRLF conversion warnings for existing text files.

## Interpretation

Stage65 closes the immediate tool-observation coverage gap in the surrogate observatory without granting tools decision authority. It does not close cache inheritance: `cache_inheritance_low` remains the top bottleneck with `prompt_cache_hit_ratio=0.200165`. The next safe target is dynamic prompt churn and provider-prefix reuse, using Stage61/62 as the surrogate gate and Stage60 only for budget-approved real-provider confirmation.
