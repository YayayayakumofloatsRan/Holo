# Stage55 Consciousness Manifold Observatory

## Goal

Stage55 extends Stage54 from visualization into high-dimensional dynamical-system observation.

The working hypothesis is geometric: visible dialogue behavior is a low-dimensional projection of a higher-dimensional subject-state process. Stage55 does not claim to prove consciousness. It creates a stricter instrument for testing whether Stage46/54 traces contain stable manifolds, loops, recurrence, local expansion, contraction, or section-crossing patterns that can later be compared across models, prompts, memory schedules, and perturbations.

## Source Of Truth

Stage55 reads the latest Stage46 `agent_eval_runs` payload, builds the Stage54 report, then derives geometry from Stage54 normalized compute vectors.

This keeps the boundary narrow:

- Stage55 does not call a provider.
- Stage55 does not start WeChat.
- Stage55 does not write self-memory.
- Stage55 does not mutate policy.
- Stage55 does not select runtime actions.
- Stage55 does not expose Holo as a downstream MCP server.

## Observatory Surfaces

`holo_host/consciousness_manifold.py` produces:

- `vector_space`: normalized Stage54 compute vectors, coordinates, dominant phases, dominant blocks, and dimensions.
- `delay_embedding`: Takens-style windowed trace embeddings over adjacent Stage54 vectors.
- `section_family`: Poincare-style slices for cache reuse, dynamic context, memory control, and latency/output.
- `local_dynamics`: adjacent vector deltas, coordinate distance, cosine similarity, curvature, path length, and axis delta energy.
- `hyperbolic_probe`: local expansion/contraction ratios, Lyapunov-style proxy, unstable-axis proxy, stable-axis proxy, and expansion/contraction events.
- `topology_signature`: recurrence edges, loop candidates, connected-component proxy, cycle-rank proxy, and torus-candidate flag.
- `boundary`: explicit no-authority limits.

The topology and hyperbolic fields are proxies over operational traces. They are intended for comparative calibration, not standalone scientific proof.

## Operator Flow

Run or reuse a Stage46 stress suite:

```powershell
python -m holo_host run-bionic-boundary-stress --offline --thread-key cli:Stage55Offline --chat-name Stage55Offline --channel cli --turns 7
```

Render the latest Stage55 observatory:

```powershell
python -m holo_host --config .holo_host.toml render-consciousness-manifold --output artifacts\stage55\stage55_current.html
```

The command writes:

- `artifacts\stage55\stage55_current.html`
- `artifacts\stage55\stage55_current.json`
- `artifacts\stage55\stage55_current_manifold.png`

`artifacts/` remains ignored by Git. The durable contract is the renderer, tests, and docs.

## Interpretation

Stage55 should be read conservatively:

- `betti1_proxy > 0` means the recurrence graph has a cycle candidate under the current projection and threshold.
- `torus_candidate=true` means there is at least one recurrence-supported loop candidate, not that a torus has been proven.
- positive `lyapunov_proxy` means adjacent vector deltas are locally expanding on average.
- negative or near-zero `lyapunov_proxy` means the local trace is contracting, cycling, or too short to distinguish.
- section piercings show how different Poincare-style cuts sample the same trajectory.

The current local render over the latest Stage46 trace produced `point_count=7`, `dimension=12`, `betti1_proxy=0`, and `loop_candidate_count=0`. That means the current run looks like a directed progression in this projection, not a closed loop or torus candidate.

## Next Direction

The next useful expansion is comparative geometry:

- render Stage55 across multiple live DeepSeek and offline Stage46 runs
- add run-to-run manifold diff metrics
- compare topology proxies against Stage46 correctness failures
- test perturbations: memory drop, cache-cold prompt, false fact injection, context-window pressure
- keep all results observational until geometry predicts behavior under perturbation
