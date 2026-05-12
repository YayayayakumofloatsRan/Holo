# Engineering Handoff Stage58

## Summary

Stage58 implements a bounded long-form surrogate geometry lab.

Stage57 made multi-run lifted-geometry calibration possible, but the real traces were too short. Stage58 generates deterministic Stage46-compatible surrogate traces from recent Stage46 seeds, labels perturbations, runs the full Stage57 calibration over those long traces, and exports HTML/JSON/PNG artifacts.

The key boundary is explicit: Stage58 proves the toolchain can run at long-trace scale. It does not prove a real consciousness manifold because the traces are surrogate data.

## Boundary

- Stage58 is observation and tooling only.
- Stage58 reads existing Stage46 operational evidence as seeds.
- Stage58 generates surrogate Stage46-compatible traces without recording them as operational eval runs.
- No provider call is performed by the renderer.
- No WeChat transport is started.
- No self-memory write, policy mutation, runtime decision authority, transport authority, downstream MCP server, or unbounded loop is added.
- `surrogate_evidence_gate.do_not_claim_real_manifold` is always true for Stage58 outputs.

## Files

- `holo_host/consciousness_longform_lab.py`
  - Adds `build_longform_geometry_lab(stage46_seed_runs, turns=420)`.
  - Adds deterministic perturbation programs: `baseline`, `memory_drop`, `false_fact`, `cache_cold`, and `context_pressure`.
  - Adds surrogate evidence gates and HTML/JSON/PNG artifact writing.
- `holo_host/cli.py`
  - Adds `render-consciousness-longform-lab`.
  - Reads recent Stage46 seed runs, builds Stage58, and writes artifacts.
- `tests/test_stage58_longform_geometry_lab.py`
  - Covers long-form trace generation, surrogate gates, artifact writing, and CLI rendering.
- `docs/STAGE58_LONGFORM_GEOMETRY_LAB.md`
  - Documents the operator workflow and interpretation.

## Verification

- `python -m pytest -q tests\test_stage58_longform_geometry_lab.py`: `3 passed`
- `python -m holo_host --config .holo_host.toml render-consciousness-longform-lab --limit 8 --turns 420 --output artifacts\stage58\stage58_current.html`: returned `ok=true`, `generated_trace_count=5`, `turns_per_trace=420`, `total_generated_turns=2100`, `geometry_score_correlation=0.983`, `surrogate_only=true`, and `do_not_claim_real_manifold=true`.
- `python -m py_compile holo_host\consciousness_longform_lab.py holo_host\consciousness_geometry_calibration.py holo_host\consciousness_dimensional_lift.py holo_host\consciousness_manifold.py holo_host\consciousness_visualization.py holo_host\cli.py`: passed.
- `python -m pytest -q tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py`: `32 passed`
- `git diff --check`: no whitespace errors; Git emitted only CRLF conversion warnings for existing text files.
- `python scripts\check_public_release_hygiene.py`: passed.
- `python -m pytest -q`: `427 passed`

## Current Artifact Paths

- `artifacts\stage58\stage58_current.html`
- `artifacts\stage58\stage58_current.json`
- `artifacts\stage58\stage58_current_longform_lab.png`

## Interpretation

Stage58 closes the tooling gap identified by Stage57.

The current render proves the pipeline can process five long traces of 420 turns each and pass them through Stage57 calibration. The surrogate Stage57 calibration reports `geometry_score_correlation=0.983`, `rank_score_correlation=0.9053`, and `longest_trace_points=420` against a recommended floor of `414`.

That makes the toolchain ready for real long-form provider evidence. It does not make a scientific claim: Stage58 keeps `do_not_claim_real_manifold=true` and `real_provider_longform_required=true`.

## Next Work

- Add an operator-approved real long-form trace runner.
- Keep provider calls inside processor fabric.
- Keep WeChat off unless separately approved.
- Carry provider/model/token provenance into Stage57/58 evidence.
- Only allow real-manifold review when the trace is real provider evidence and passes trace-depth plus predictive gates.
