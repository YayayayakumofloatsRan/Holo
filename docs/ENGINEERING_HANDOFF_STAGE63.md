# Engineering Handoff Stage63

## Summary

Stage63 implements a cache inheritance spine for the bionic memory scheduler.

Stage62 ranked cache inheritance as the strongest bottleneck. Stage63 responds by moving stable bionic operating schema into a provider-cache-friendly prefix, excluding salience-specific values from that stable prefix, preserving cache evidence in Stage46 compact debug, and letting Stage61 simulation reward larger stable-prefix evidence without changing scenario capability scores.

## Boundary

- Stage63 is prompt-scheduling and diagnostic only.
- It performs no provider call and starts no WeChat transport.
- It does not write live self-memory, mutate policy, widen transport authority, grant runtime decision authority, expose Holo as a downstream MCP server, add a second decision layer, or add an unbounded loop.
- Current turns, recent thread windows, active working state, and per-turn recall remain dynamic.
- Cache-spine data is evidence for scheduling and evaluation; it is not decision authority.

## Files

- `holo_host/bionic_memory_scheduler.py`
  - Adds `stage63_cortical_cache_spine_v1`.
  - Extends `provider_prefix_lines` with stable cache-spine lines.
  - Adds `cache_inheritance` telemetry and excludes recall-budget/salience values from the stable prefix.
- `holo_host/context_scheduler.py`
  - Reports cache-inheritance mode, prefix share, stable/dynamic token estimates, and cache-spine line count.
- `holo_host/bionic_boundary_stress.py`
  - Preserves cache-inheritance evidence in compact Stage46 debug.
  - Updates the offline scripted runner to simulate cache behavior from rendered prompt prefix/dynamic split.
- `holo_host/bionic_simulation_lab.py`
  - Uses prompt partition or context schedule prefix/dynamic tokens to model cache-inheritance gain in Stage61 surrogate turns.
- `tests/test_stage63_cache_inheritance_spine.py`
  - Covers stable cache-spine generation, salience exclusion from stable prefix, Stage61 cache-response behavior, and compact debug preservation.
- `docs/STAGE63_CACHE_INHERITANCE_SPINE.md`
  - Operator workflow, current evidence, boundary, and interpretation.

## Verification

- `python -m pytest -q tests\test_stage63_cache_inheritance_spine.py`: `4 passed`
- `python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\context_scheduler.py holo_host\bionic_boundary_stress.py holo_host\bionic_simulation_lab.py holo_host\bionic_capability_observatory.py holo_host\cli.py`: passed
- `python -m pytest -q tests\test_stage63_cache_inheritance_spine.py tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py tests\test_stage61_bionic_simulation_lab.py tests\test_stage62_bionic_capability_observatory.py`: `41 passed`
- `python -m pytest -q tests\test_stage63_cache_inheritance_spine.py tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py tests\test_stage61_bionic_simulation_lab.py tests\test_stage62_bionic_capability_observatory.py tests\test_stage60_trace_campaign.py tests\test_stage59_provider_trace.py tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_processor_fabric.py`: `83 passed`
- `python -m holo_host --config .holo_host.toml run-bionic-boundary-stress --thread-key cli:Stage63CacheStable-20260513 --chat-name Stage63CacheStable-20260513 --channel cli --turns 7 --offline`: passed
- `python -m holo_host --config .holo_host.toml run-bionic-simulation-lab --limit 1 --scenarios 9 --turns 240 --output artifacts\stage63\stage63_stage61_cache_spine_stable.html`: returned `prompt_cache_hit_ratio=0.204046`, `average_provider_cache_prefix_tokens=1202.54`, `average_provider_cache_dynamic_tokens=2605.28`, `average_latency_ms=6267.74`, `p95_latency_ms=7506.0`, and `improvement_count=4`
- `python -m holo_host --config .holo_host.toml evaluate-bionic-capability-observatory --limit 1 --scenarios 9 --turns 240 --output artifacts\stage63\stage63_stage62_cache_spine_stable.html`: returned `aggregate_score=0.659837`, `cache_inheritance=0.370993`, `latency_residual=0.578316`, `bottleneck_count=8`, `surrogate_only=true`, and `do_not_claim_real_manifold=true`
- `python -m pytest -q`: `448 passed`
- `python scripts\check_public_release_hygiene.py`: passed
- `git diff --check`: no whitespace errors; Git emitted only CRLF conversion warnings for existing text files

## Current Artifact Paths

- `artifacts\stage63\stage63_stage46_cache_spine_stdout.jsonl`
- `artifacts\stage63\stage63_stage61_cache_spine_stable.html`
- `artifacts\stage63\stage63_stage61_cache_spine_stable.json`
- `artifacts\stage63\stage63_stage61_cache_spine_stable_simulation_lab.png`
- `artifacts\stage63\stage63_stage61_cache_spine_stable_turns.jsonl`
- `artifacts\stage63\stage63_stage62_cache_spine_stable.html`
- `artifacts\stage63\stage63_stage62_cache_spine_stable.json`
- `artifacts\stage63\stage63_stage62_cache_spine_stable_capability_observatory.png`

## Interpretation

Stage63 is a structural cache improvement, not a full closure. Stable-prefix evidence improved substantially, and the latest Stage62 aggregate improved versus the Stage62 baseline, but `cache_inheritance_low` remains the top ranked bottleneck. The next safe target is dynamic prompt churn: reduce dynamic payload size and volatility while preserving grounding, recall, and bounded tool-observation capability.
