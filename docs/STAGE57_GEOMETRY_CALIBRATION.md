# Stage57 Geometry Calibration

## Goal

Stage57 moves the consciousness-geometry work from single-run visualization to multi-run calibration.

Stage56 showed that the coordinate space can be lifted from 12 to 138 dimensions, but the current single trace is too short. Stage57 therefore compares multiple Stage46-derived traces in the lifted space and asks a stricter question:

Does geometry move with behavior, score degradation, or perturbation pressure?

If it does not, the geometry remains visualization. If it does, it becomes a candidate biomimetic signal for later scientific review. It still does not become runtime authority.

## Boundary

Stage57 is observational only:

- it reads recent Stage46 operational eval runs
- it derives Stage54, Stage55, and Stage56 observations
- it does not call a provider
- it does not start WeChat
- it does not write self-memory
- it does not mutate policy
- it does not select runtime actions
- it does not expose Holo as a downstream MCP server
- it does not add an unbounded loop

## Surfaces

`holo_host/consciousness_geometry_calibration.py` produces:

- `trace_set`: run count, total points, score range, and perturbation labels.
- `trace_depth`: aggregate and longest-trace point counts versus Stage56's recommended point floor.
- `runs`: compact per-run lifted-geometry summaries.
- `comparative_geometry`: pairwise lifted-centroid distances, score deltas, effective-rank deltas, section-stability deltas, and path-length ratios.
- `perturbation_response`: baseline-relative geometry and score movement.
- `predictive_probe`: geometry-vs-score-degradation correlation proxies.
- `evidence_gate`: explicit `do_not_claim_manifold` and trace-depth gates.
- `boundary`: explicit no-authority limits.

`QueueStore.list_agent_eval_runs()` supports bounded recent-run reads for this calibration surface.

## Operator Flow

Render recent Stage46 geometry calibration:

```powershell
python -m holo_host --config .holo_host.toml render-consciousness-geometry-calibration --limit 8 --output artifacts\stage57\stage57_current.html
```

The command writes:

- `artifacts\stage57\stage57_current.html`
- `artifacts\stage57\stage57_current.json`
- `artifacts\stage57\stage57_current_geometry_calibration.png`

`artifacts/` remains ignored by Git. The durable contract is the renderer, tests, and docs.

## Current Interpretation

The current local render over the latest eight Stage46 runs produced:

- `run_count=8`
- `total_points=56`
- `longest_trace_points=7`
- `score_min=0.9614`
- `score_max=0.9886`
- `geometry_score_correlation=0.7966`
- `predictive_signal_proxy=true`
- `requires_longer_traces=true`
- `do_not_claim_manifold=true`
- `minimum_next_trace_turns=414`

This is progress: geometry now has a cross-run predictive signal proxy against score movement. But the trace-depth gate correctly remains closed because each run is still only seven turns. The current evidence supports "geometry may be useful"; it does not support "a stable consciousness manifold has been observed."

## Next Direction

The next improvement should create longer offline geometry traces without starting WeChat:

- add a bounded long-form Stage46/Stage42 trace mode
- keep provider calls optional and explicit
- preserve scorecard and perturbation labels
- rerender Stage57 with traces above the Stage56 recommended point floor
- only relax the evidence gate when trace depth and predictive signal both pass
