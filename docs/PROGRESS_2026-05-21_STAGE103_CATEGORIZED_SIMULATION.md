# Stage103 Categorized Biomimetic Simulation - 2026-05-21

## Objective

The Stage102 workbench made recall candidate motion visible, but the live telemetry was too sparse for a smooth biomimetic trajectory. Stage103 adds categorized, topic-based simulation sweeps so the workbench can render continuous semantic-affective movement at research scale.

The simulator is offline and redacted. It does not call a provider and does not claim hidden reasoning. It generates observable proxy frames for repeatable visualization and paper-facing experiments.

## Implemented

Added:

- `holo_host/biomimetic_simulation.py`
- CLI command:

```powershell
python -m holo_host simulate-biomimetic-telemetry --topics-per-category 4 --turns-per-topic 24 --seed 103 --batch-id stage103-categorized-topic-sweep-final
```

Simulation catalog categories:

- `affective_regulation`
- `autobiographical_recall`
- `task_world`
- `semantic_inference`
- `multimodal_grounding`
- `self_model_boundary`

Each category contains multiple topics. The simulator interpolates semantic-affective state across topic probes and writes append-only `simulation_turn` telemetry frames.

## Visualization Changes

The workbench now:

- prefers the latest simulation batch when one exists
- marks trajectory source as `biomimetic_simulation`
- exposes category/topic labels on frames
- adds simulation summary metrics:
  - batch id
  - category count
  - topic count
  - continuity max delta
  - large jump count
- adds topic/category topology nodes
- colors phase-space points by category
- keeps recall microframes small for simulation batches so topic continuity stays readable

## Real Sweep

Command:

```powershell
python -m holo_host simulate-biomimetic-telemetry --topics-per-category 4 --turns-per-topic 24 --seed 103 --batch-id stage103-categorized-topic-sweep
python -m holo_host visualize-biomimetic-system
```

Result:

```text
sim_frames=576
categories=6
topics=24
sim_max_delta=0.0599
source=biomimetic_simulation
visual_frames=2304
visual_batch=stage103-categorized-topic-sweep-final
visual_max_delta=0.0691
visual_large_jumps=0
html_path=D:\Holo\holo\artifacts\stage100\stage100_biomimetic_system_workbench.html
```

Before Stage103, the current workbench payload had:

```text
frames=30
max_delta=0.78
large_jumps=1
```

So the category/topic simulation sweep reduces the visible maximum jump from `0.78` to `0.0691` in the rendered trajectory while restoring all `6` categories and `24` topics to the payload.

## Verification

Focused tests:

```powershell
pytest -q tests/test_biomimetic_simulation.py tests/test_biomimetic_visualization.py tests/test_biomimetic_telemetry.py --basetemp .holo_runtime\pytest-tmp
```

Result:

```text
14 passed
```

Broader regression:

```powershell
pytest -q tests/test_biomimetic_simulation.py tests/test_biomimetic_telemetry.py tests/test_biomimetic_visualization.py tests/test_reply_api_auth.py tests/test_memory_fabric.py tests/test_memory_doctor.py tests/test_memory_promotion.py tests/test_cli_chat.py tests/test_memory_admin.py --basetemp .holo_runtime\pytest-tmp
```

Result:

```text
41 passed
```

WSL smoke against the current Windows-backed checkout:

```bash
cd /mnt/d/Holo/holo
python3 -m holo_host simulate-biomimetic-telemetry --topics-per-category 1 --turns-per-topic 4 --seed 203 --batch-id stage103-wsl-smoke
python3 -m holo_host visualize-biomimetic-system
```

Result:

```text
sim_frames=24
categories=6
topics=6
max_delta=0.0499
large_jumps=0
source=biomimetic_simulation
```

After the WSL smoke, the Windows workbench was regenerated with the larger `stage103-categorized-topic-sweep-final` batch so the browser artifact remains on the large categorized sweep.

## Boundary

- Simulation telemetry is observational and redacted.
- It does not modify action selection.
- It does not become a second decision layer.
- It does not contain raw user text, raw memory text, raw node ids, graph labels, prompts, or reply text.
- It is a research instrument for visualization and repeatable ablation design, not evidence of real emotion or consciousness.

## Next Work

1. Run provider-backed categorized tests against the same catalog.
2. Add per-category continuity and separation metrics to the workbench.
3. Add ablation tags for memory-drop, deep-recall-disabled, and promotion-disabled.
4. Add static paper export panels from the categorized simulation payload.
