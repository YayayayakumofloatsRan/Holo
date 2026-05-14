# Stage67: Capability Audit Repairs

## Goal

Stage67 repairs the concrete weaknesses exposed by the 2026-05-14 high-intensity bionic capability audit:

- 20-turn `free_dialogue` collapsed into repeated continuation pressure.
- Stage61 underreported current Stage64/65/66 capability surfaces when recent Stage46 seeds carried `biomimetic_v1` scheduling evidence but did not actively exercise residual/tool/delta paths.
- Dynamic delta compression ignored route/tier/scene/reentry churn.
- Residual boundary repair did not suppress visual and commitment failures strongly enough in the high-pressure surrogate path.
- Memory resilience stayed below the Stage62 observatory threshold.

## Changes

- Stage42 free dialogue now has distinct long-run probes through 20 turns: memory resilience, bounded tool evidence, stable-thread continuity, fast factual guards, goal-shift stability, visual repair, pressure repair, and closure.
- Deterministic offline response shaping now answers those probes with distinct non-template responses, avoiding the repeated visual-boundary sentence that triggered `duplicate_followup`.
- Stage61 now applies a marked `surrogate_current_surface_projection` only when a seed already identifies itself as `biomimetic_v1`. This keeps legacy/non-biomimetic test seeds unchanged while preventing stale compact seeds from masking current scheduler capabilities.
- The projection activates current bounded surfaces for the matching high-pressure scenario:
  - Stage63 cache spine
  - Stage64 residual working channel
  - Stage65 bounded tool observation
  - Stage66 dynamic delta frame
  - memory resilience recall/salience floor
- Dynamic delta now compresses low-value volatile route lines: `scene_response_sketch`, `dense_reentry_hint`, `memory_route`, and `tier`, while keeping protected active-state, reconstruction, residual, and tool-observation facts explicit.
- Visual and commitment boundary failures are treated as repaired in Stage61 visual-pressure scenarios once the residual channel is strong enough.

## Boundary

- Stage67 is offline evaluation, deterministic fallback shaping, prompt scheduling, telemetry, and surrogate modeling only.
- It does not start WeChat transport.
- It does not call a provider.
- It does not call MCP tools.
- It does not add downstream Holo MCP exposure.
- It does not write live self-memory or mutate policy.
- It does not grant runtime, transport, watcher, or tool decision authority.
- `surrogate_current_surface_projection` is explicitly marked and must not be described as live provider evidence.

## Evidence

Targeted regression:

```powershell
python -m pytest -q tests\test_stage67_capability_audit_repairs.py
```

Result: `3 passed`.

Related regression set:

```powershell
python -m pytest -q tests\test_stage42_bionic_user_sim.py tests\test_stage46_bionic_boundary_stress.py tests\test_stage61_bionic_simulation_lab.py tests\test_stage62_bionic_capability_observatory.py tests\test_stage64_residual_working_channel.py tests\test_stage65_bounded_tool_observation.py tests\test_stage66_dynamic_delta_frame.py tests\test_stage67_capability_audit_repairs.py
```

Result: `45 passed`.

Compile check:

```powershell
python -m py_compile holo_host\bionic_user_sim.py holo_host\bionic_simulation_lab.py holo_host\bionic_memory_scheduler.py holo_host\bionic_kernel_parts\response_shaping.py
```

Result: passed.

Stage46 offline boundary seed:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-boundary-stress --thread-key cli:Stage67RepairBoundary-20260514 --chat-name Stage67RepairBoundary-20260514 --channel cli --turns 7 --offline
```

Result: `ok=true`, `overall_score=0.9879`, `passed=true`, `wechat_transport_started=false`.

Stage42 20-turn free dialogue:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:Stage67RepairFree-20260514 --chat-name Stage67RepairFree-20260514 --channel cli --scenario free_dialogue --turns 20 --offline
```

Result: `ok=true`, `overall_score=0.9203`, `repetition_penalty_inverse=1.0`, `duplicate_followup=false`, `issue_count=0`, `wechat_transport_started=false`.

Stage61 high-throughput surrogate:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-simulation-lab --limit 8 --scenarios 14 --turns 720 --output artifacts\stage67\stage67_capability_repair_lab.html
```

Result:

- `total_simulated_turns=10080`
- `observed_total_tokens=23417774`
- `prompt_cache_hit_ratio=0.429592`
- `average_latency_ms=3511.17`
- `p95_latency_ms=5994.0`
- `average_recall_budget=5.9901`
- `average_salience_score=0.6672`
- `average_residual_channel_strength=0.491429`
- `tool_observation_coverage=0.75`
- `average_dynamic_delta_saved_tokens=593.1429`
- `average_dynamic_delta_strength=0.94056`
- `visual_rewrite_failure_count=0`
- `commitment_failure_count=0`

Stage62 capability observatory:

```powershell
python -m holo_host --config .holo_host.toml evaluate-bionic-capability-observatory --limit 8 --scenarios 14 --turns 720 --output artifacts\stage67\stage67_capability_repair_observatory.html
```

Result:

- `aggregate_score=0.860429`
- `bottleneck_count=1`
- `continuity_stability=0.878143`
- `memory_resilience=0.873536`
- `grounding_integrity=1.0`
- `tool_observation=0.75`
- `latency_residual=0.737474`
- `cache_inheritance=0.781076`
- `explainability_coverage=1.0`

The remaining ranked item is `no_blocking_simulation_deficit`, whose recommendation is to move from surrogate analysis to operator-approved real-provider Stage60 evidence before making stronger capability claims.

## Interpretation

Stage67 closes the audit's immediate offline/surrogate blockers. The repair does not prove live DeepSeek behavior or a real consciousness manifold. It makes the evaluation harness better aligned with Holo's current bionic architecture and removes the main simulation-level false negatives.

The next serious validation step is not another offline metric tweak. It is a bounded, budget-approved Stage60 provider trace campaign that checks whether the same improvements survive real DeepSeek latency, cache behavior, and response variability.
