# Stage63 Cache Inheritance Spine

Stage63 improves Holo's cache inheritance path after Stage62 ranked `cache_inheritance_low` as the top bottleneck.

The goal is to increase stable provider-prefix reuse without moving decision authority out of the WSL subject runtime and without hiding dynamic evidence from the model. Stage63 adds a cortical cache spine to the bionic memory scheduler, makes cache-inheritance telemetry visible in context scheduling and Stage46 compact debug, and teaches Stage61 simulation to respond to larger stable-prefix evidence.

## Boundary

- Stage63 is a prompt-scheduling and diagnostic improvement.
- It does not call a provider by itself or start WeChat.
- It does not write live self-memory, mutate policy, widen transport authority, expose Holo as a downstream MCP server, add runtime decision authority, add a second decision layer, or create an unbounded loop.
- The cache spine carries stable schemas only. Current user turns, recent thread windows, active working state, and per-turn recall remain dynamic.
- Salience-specific values such as recall budget are excluded from the provider prefix so pressure changes do not churn the stable-prefix digest.

## Implementation

- `build_bionic_memory_schedule()` now emits `cache_inheritance.mode=stage63_cortical_cache_spine_v1`.
- `provider_prefix_lines` now include stable cortical schema plus cache-spine lines for memory architecture, grounding, residual fast-channel boundaries, upstream-tool observation boundaries, and self-memory authority boundaries.
- `plan_processor_context()` now reports `cache_inheritance_mode`, `cache_inheritance_prefix_share`, stable/dynamic token estimates, and cache-spine line count.
- Stage46 compact debug preserves cache-inheritance evidence.
- Stage61 simulation now uses prompt partition or context-schedule prefix/dynamic tokens to estimate cache-inheritance gain in generated surrogate turns.
- Stage46 offline scripted runs now simulate provider-cache behavior from rendered prompt prefix/dynamic split rather than fixed cache counts.

## Current Evidence

On 2026-05-13:

- `run-bionic-boundary-stress --offline` passed for `cli:Stage63CacheStable-20260513` without starting WeChat.
- `run-bionic-simulation-lab --limit 1 --scenarios 9 --turns 240` wrote `artifacts\stage63\stage63_stage61_cache_spine_stable.html`, `.json`, `_simulation_lab.png`, and `_turns.jsonl`.
- Stage61 latest-seed telemetry reported `prompt_cache_hit_ratio=0.204046`, `average_provider_cache_prefix_tokens=1202.54`, `average_provider_cache_dynamic_tokens=2605.28`, `average_latency_ms=6267.74`, `p95_latency_ms=7506.0`, and `improvement_count=4`.
- The comparable Stage61 baseline artifact reported `prompt_cache_hit_ratio=0.203306`, `average_provider_cache_prefix_tokens=441.23`, `average_provider_cache_dynamic_tokens=1288.76`, `average_latency_ms=7334.77`, and `p95_latency_ms=17120.0`.
- `evaluate-bionic-capability-observatory --limit 1 --scenarios 9 --turns 240` wrote `artifacts\stage63\stage63_stage62_cache_spine_stable.html`, `.json`, and `_capability_observatory.png`.
- Stage62 latest-seed observatory reported `aggregate_score=0.659837`, `cache_inheritance=0.370993`, `latency_residual=0.578316`, `bottleneck_count=8`, `surrogate_only=true`, and `do_not_claim_real_manifold=true`.
- The comparable Stage62 baseline artifact reported `aggregate_score=0.579427`, `cache_inheritance=0.369647`, `latency_residual=0.0`, and `bottleneck_count=9`.

## Interpretation

Stage63 improves the stable-prefix structure and makes cache inheritance measurable across the runtime, stress harness, simulation lab, and capability observatory. It is not a full cache-bottleneck closure: `cache_inheritance_low` remains the top ranked bottleneck. The next improvement should reduce dynamic prompt churn and improve bounded tool observation without weakening grounding or capability score.
