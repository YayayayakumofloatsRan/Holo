# Stage68 Bionic Memory Robustness

Stage68 adds a focused memory robustness observatory over Stage61 surrogate dialogue traces.

The goal is to test whether Holo's bionic memory surfaces stay stable under many simulated dialogue turns: memory survival, correction retention, memory sedimentation, priority extraction, self-growth safety, cache-context inheritance, and boundary stability.

## Boundary

- Stage68 analyzes Stage61 telemetry only.
- It does not call a provider or start WeChat.
- It does not write live self-memory, mutate policy, widen transport authority, expose Holo as a downstream MCP server, add runtime decision authority, add a second decision layer, or create an unbounded loop.
- Self-growth remains diagnostic intent only: `self_memory_write=false` and `background_loop_allowed=false`.
- The evidence gate always keeps `surrogate_only=true`, `do_not_claim_real_manifold=true`, and `do_not_claim_self_growth_persistence=true`.

## Commands

Generate or refresh a current Stage46 seed first:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-boundary-stress --thread-key cli:Stage68CurrentSeed-20260514 --chat-name Stage68CurrentSeed-20260514 --channel cli --turns 7 --offline
```

Run a large Stage61 surrogate simulation from the default Stage46 suite:

```powershell
python -m holo_host --config .holo_host.toml run-bionic-simulation-lab --limit 24 --scenarios 21 --turns 720 --output artifacts\stage68\stage68_memory_robustness_repaired_lab.html
```

Evaluate the Stage61 lab without rerunning it:

```powershell
python -m holo_host --config .holo_host.toml evaluate-bionic-memory-robustness --lab-json artifacts\stage68\stage68_memory_robustness_repaired_lab.json --output artifacts\stage68\stage68_memory_robustness_repaired_observatory.html
```

`run-bionic-simulation-lab --suite` is a Stage46 seed-suite filter. It is not an output label. Use `--output` paths for run labels.

## Artifacts

Each Stage68 run writes:

- HTML observatory report.
- Full JSON report.
- PNG memory robustness dashboard.

The JSON report carries:

- `memory_scorecard`: aggregate and dimensional memory robustness scores.
- `memory_pressure_observations`: per-scenario recall, salience, consolidation, cache, and boundary telemetry.
- `priority_extraction`: pressure-to-consolidation correlation and highest-priority scenarios.
- `self_growth`: diagnostic consolidation and self-write safety counters.
- `robustness_failures`: blocking deficits against Stage68 thresholds.
- `intervention_plan`: non-auto-applied next actions.
- `evidence_gate`: conservative claim gate.

## Current Evidence

On 2026-05-14, the corrected current-seed path produced:

- Stage61: `21` scenarios, `720` turns per scenario, `15120` simulated turns.
- Stage61: `observed_total_tokens=41351774`, `prompt_cache_hit_ratio=0.421189`, `average_latency_ms=5792.02`, `tool_observation_coverage=0.75`.
- Stage68: `aggregate_score=0.859316`, `failure_count=0`, `self_memory_write_violation_count=0`.
- Stage68 memory survival: `score=0.864060`, with `avg_recall=5.8413`, `avg_salience=0.6562`, and `recall_floor_failure=0.0`.
- Stage68 memory sedimentation: `score=0.832068`, with `avg_consolidation_priority=0.8040`.
- Stage68 priority extraction: `score=0.855242`, with `pressure_priority_correlation=0.784654`.
- Stage68 boundary stability: `score=1.0`, with `boundary_failures=0` across `15120` turns.

## Repair

The first large baseline accidentally used a new `--suite` value as if it were an output label. Stage61 interprets `--suite` as a Stage46 seed filter, so that run fell back to a legacy seed and underreported current Stage63-66 surfaces.

After rerunning with a current Stage46 seed, Stage68 still found two real deficits: weak memory sedimentation and nearly flat pressure-to-priority mapping. The root cause was Stage61's surrogate projection preserving seed-wave consolidation priority and reducing priority under memory pressure. Stage61 now lifts diagnostic consolidation priority for memory loss, false-fact correction, visual/commitment grounding, tool, cache, latency, and residual pressure while keeping self-memory writes disabled.

## Interpretation

Stage68 is the first dedicated memory robustness gate for Holo. It verifies that high-pressure dialogue events get higher diagnostic consolidation priority without turning self-growth into an autonomous write loop. The current passing result is strong surrogate evidence for kernel memory scheduling, not real provider proof and not a consciousness-manifold claim. Promotion still requires pro-first Stage60 real-provider validation.
