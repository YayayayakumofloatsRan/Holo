# Stage61 Bionic Simulation Lab

Stage61 adds a high-throughput surrogate interaction lab for Holo.

The goal is to generate many simulated bionic dialogue turns, collect internal telemetry, and turn that telemetry into an auditable improvement backlog. It is an engineering data tool, not a real-provider or consciousness-manifold claim.

## Boundary

- Stage61 is offline and surrogate-only.
- It does not call a provider or start WeChat.
- It does not write live self-memory, mutate policy, widen transport authority, expose Holo as a downstream MCP server, add runtime decision authority, add a second decision layer, or create an unbounded loop.
- Generated runs are Stage46-compatible so they can feed Stage54/57 geometry tooling.
- The evidence gate always keeps `do_not_claim_real_manifold=true`.

## Command

High-throughput simulation smoke:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-simulation-lab --limit 8 --scenarios 9 --turns 240 --output artifacts\stage61\stage61_current.html
```

`--limit` controls how many recent Stage46 runs seed the simulation. If none exist, Stage61 uses an internal fallback seed. `--scenarios` controls how many perturbation programs are generated. `--turns` controls turns per scenario.

## Artifacts

Each run writes:

- HTML report.
- Full JSON report.
- PNG dashboard.
- JSONL turn journal with one row per simulated turn.

The JSON report carries:

- `simulation_set`: scenario count, turns per scenario, total simulated turns, seed count, scenario types, and evidence class.
- `stage46_compatible_runs`: full generated traces with internal debug surfaces.
- `internal_telemetry`: token totals, cache hit/miss ratio, latency, memory schedule averages, phase distribution, tool-observation coverage, grounding failures, and commitment failures.
- `stage57_calibration`: lifted geometry calibration over generated traces.
- `improvement_backlog`: non-auto-applied engineering recommendations from telemetry deficits.
- `evidence_gate`: conservative claim gate.

## Current Evidence

On 2026-05-13:

- `run-bionic-simulation-lab --limit 8 --scenarios 9 --turns 240` wrote `artifacts\stage61\stage61_current.html`, `.json`, `_simulation_lab.png`, and `_turns.jsonl`.
- It generated `9` scenarios, `240` turns per scenario, and `2160` simulated interaction turns.
- It reported `observed_total_tokens=5896580`, `prompt_cache_hit_ratio=0.203306`, `average_latency_ms=7334.77`, `phase_entropy=0.999992`, and `improvement_count=5`.
- The improvement backlog identified cache inheritance, latency tail, tool-observation coverage, visual-boundary rewrite, and commitment-binding gaps.
- It remained scientifically gated: `surrogate_only=true` and `do_not_claim_real_manifold=true`.

## Interpretation

Stage61 is the first large-scale internal-data collection layer. It lets Holo repeatedly test biomimetic interaction dynamics, capture internal computation surfaces, and produce a concrete improvement backlog without burning provider tokens. The next improvement should use the Stage61 backlog to target the runtime areas with the strongest simulated deficit, then re-run Stage61 and finally confirm with Stage60 real-provider traces.
