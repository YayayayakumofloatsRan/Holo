# Stage58 Long-Form Geometry Lab

## Goal

Stage58 makes the consciousness-geometry toolchain operationally mature enough to stress-test long traces.

Stage57 showed a promising geometry-score movement signal across recent Stage46 runs, but each real trace was still only seven turns. Stage58 adds a bounded long-form surrogate lab that can generate deterministic Stage46-compatible traces with perturbation labels, feed them through Stage57, and verify that the visualization and calibration pipeline works at the target trace depth.

This is a tooling stage, not scientific proof.

## Boundary

Stage58 is observational and surrogate-only:

- it reads existing Stage46 operational evidence as seeds
- it generates deterministic Stage46-compatible surrogate traces
- it derives Stage57 calibration from those surrogate traces
- it does not call a provider
- it does not start WeChat
- it does not write self-memory
- it does not mutate policy
- it does not select runtime actions
- it does not expose Holo as a downstream MCP server
- it does not add an unbounded loop

Surrogate traces can validate tool readiness. They cannot validate a real consciousness manifold.

## Surfaces

`holo_host/consciousness_longform_lab.py` produces:

- `longform_trace_set`: generated trace count, turns per trace, perturbation labels, seed count, and evidence class.
- `generated_runs`: compact summaries of surrogate Stage46-compatible runs.
- `stage57_calibration`: the full Stage57 multi-run calibration over the generated traces.
- `surrogate_evidence_gate`: explicit real-provider claim blocker.
- `tool_readiness`: whether long-form generation, perturbation labels, Stage57 calibration, and artifact export are ready.
- `boundary`: explicit no-authority limits.

## Operator Flow

Render the long-form geometry lab from recent Stage46 seeds:

```powershell
python -m holo_host --config .holo_host.toml render-consciousness-longform-lab --limit 8 --turns 420 --output artifacts\stage58\stage58_current.html
```

The command writes:

- `artifacts\stage58\stage58_current.html`
- `artifacts\stage58\stage58_current.json`
- `artifacts\stage58\stage58_current_longform_lab.png`

`artifacts/` remains ignored by Git. The durable contract is the renderer, tests, and docs.

## Current Interpretation

The current local render produced:

- `generated_trace_count=5`
- `turns_per_trace=420`
- `total_generated_turns=2100`
- Stage57 `longest_trace_points=420`
- Stage57 `recommended_min_points=414`
- Stage57 `geometry_score_correlation=0.983`
- Stage57 `rank_score_correlation=0.9053`
- Stage57 `stage57_do_not_claim_manifold=false` inside the surrogate-only calibration
- Stage58 `do_not_claim_real_manifold=true`
- Stage58 `real_provider_longform_required=true`

This means the toolchain can now operate at the required long-trace scale. It also means the remaining blocker has changed: the next needed evidence is real long-form provider traces, not more surrogate plotting.

## Next Direction

The next stage should add an explicit operator-approved real long-form trace runner:

- provider calls must remain inside the processor fabric
- WeChat must remain off unless separately approved
- trace count, turn count, token budget, and provider/model must be explicit
- generated evidence must carry provider provenance
- Stage58's surrogate gate should only be bypassed by real provider long-form evidence
