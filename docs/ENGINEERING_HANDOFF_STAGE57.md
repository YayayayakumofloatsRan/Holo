# Engineering Handoff Stage57

## Summary

Stage57 implements multi-run geometry calibration over recent Stage46 traces.

Stage56 solved the immediate coordinate-dimension bottleneck by lifting each trace point from 12 to 138 dimensions. Stage57 addresses the next bottleneck: a single seven-turn trace is not enough to validate a stable high-dimensional structure. The new calibration surface compares multiple lifted Stage56 observations and checks whether geometry moves with score degradation or perturbation pressure.

## Boundary

- Stage57 is observation and analysis only.
- Stage57 reads existing Stage46 operational evidence and derives Stage54/55/56 observations.
- No provider call is performed by the renderer.
- No WeChat transport is started.
- No self-memory write, policy mutation, runtime decision authority, transport authority, downstream MCP server, or unbounded loop is added.

## Files

- `holo_host/consciousness_geometry_calibration.py`
  - Adds `build_geometry_calibration(stage46_runs)`.
  - Adds pairwise lifted-geometry comparison, baseline-relative perturbation response, geometry-vs-score predictive probes, evidence gates, and HTML/JSON/PNG artifact writing.
- `holo_host/store.py`
  - Adds bounded `QueueStore.list_agent_eval_runs(stage, suite, limit)` for recent operational eval reads.
- `holo_host/cli.py`
  - Adds `render-consciousness-geometry-calibration`.
  - Reads recent Stage46 runs, derives Stage54/55/56 observations, and writes Stage57 artifacts.
- `tests/test_stage57_geometry_calibration.py`
  - Covers synthetic baseline/perturbation calibration, artifact writing, and CLI rendering from recent Stage46 rows.
- `docs/STAGE57_GEOMETRY_CALIBRATION.md`
  - Documents the operator workflow and interpretation.

## Verification

- `python -m pytest -q tests\test_stage57_geometry_calibration.py`: `3 passed`
- `python -m holo_host --config .holo_host.toml render-consciousness-geometry-calibration --limit 8 --output artifacts\stage57\stage57_current.html`: returned `ok=true`, `run_count=8`, `total_points=56`, `longest_trace_points=7`, `geometry_score_correlation=0.7966`, `requires_longer_traces=true`, and `do_not_claim_manifold=true`.
- `python -m py_compile holo_host\consciousness_geometry_calibration.py holo_host\consciousness_dimensional_lift.py holo_host\consciousness_manifold.py holo_host\consciousness_visualization.py holo_host\cli.py holo_host\store.py`: passed.
- `python -m pytest -q tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py`: `29 passed`
- `git diff --check`: no whitespace errors; Git emitted only CRLF conversion warnings for existing text files.
- `python scripts\check_public_release_hygiene.py`: passed.
- `python -m pytest -q`: `424 passed`

## Current Artifact Paths

- `artifacts\stage57\stage57_current.html`
- `artifacts\stage57\stage57_current.json`
- `artifacts\stage57\stage57_current_geometry_calibration.png`

## Interpretation

Stage57 found a useful but still insufficient signal.

The latest eight Stage46 runs produce a cross-run geometry-score correlation proxy of `0.7966`, which suggests lifted geometry is tracking some capability/stability movement. However, the longest individual trace is still only seven points, while Stage56's current recommended minimum remains `414`. The evidence gate therefore keeps `do_not_claim_manifold=true`.

The correct reading is: geometry is now a candidate biomimetic signal worth testing with longer traces, not proof of a stable consciousness manifold.

## Next Work

- Add bounded long-form offline trace generation for geometry observation.
- Preserve perturbation labels and scorecards for calibration.
- Rerender Stage57 with traces above the Stage56 point floor.
- Keep the evidence gate closed unless both trace depth and predictive movement pass.
