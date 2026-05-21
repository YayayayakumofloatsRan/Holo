# Stage102 Recall Trajectory Telemetry - 2026-05-21

## Objective

Stage101 recorded one redacted telemetry frame per observable event. Stage102 makes recall movement visible inside those events.

The goal is to show how Holo moves through graph, vector, activation, and rerank candidates while forming a reply or diagnostic memory packet, without storing raw memory text or hidden reasoning.

## Implemented

Added to `holo_host/biomimetic_telemetry.py`:

- `build_recall_trajectory(...)`
- `holo.recall_trajectory.v1`
- recall observables:
  - `recall_tier`
  - `recall_query_focus`
  - `recall_candidate_count`
  - `recall_stage_count`
  - `recall_max_score`
  - `recall_mean_score`
  - `graph_hit_count`
  - `vector_hit_count`
  - `rerank_hit_count`
- recall topology references:
  - `recall_stage:<stage>`
  - `recall_node:<hashed-node>`

Integrated telemetry recording into:

- CLI `inspect-mind`
- CLI `trace-recall`
- CLI `trace-hybrid-recall`
- HTTP `GET /inspect-mind`
- HTTP `GET /trace-recall`
- HTTP `GET /trace-hybrid-recall`

Expanded visualization in `holo_host/biomimetic_visualization.py`:

- event frames remain visible
- recall trajectory candidates become microframes
- microframes carry:
  - stage
  - hashed candidate id
  - redacted score
  - memory class
  - local projection movement

## Redaction Contract

Stage102 stores:

- query length/hash through the Stage101 input signature
- candidate hashes
- scores
- stages
- rank
- memory class
- source class
- reason counts
- aggregate stage counts

Stage102 does not store:

- raw query text
- raw memory text
- raw node ids
- raw graph labels
- raw reason strings
- prompt text
- reply text

## Verification

Focused tests:

```powershell
pytest -q tests/test_biomimetic_telemetry.py tests/test_biomimetic_visualization.py tests/test_reply_api_auth.py --basetemp .holo_runtime\pytest-tmp
```

Result:

```text
15 passed
```

Real Windows recall smoke:

```powershell
python -m holo_host trace-hybrid-recall --query "你还记得重新上线前吗" --thread-key holo_cli:main --chat-name Holo --channel holo_cli --limit 5
python -m holo_host show-biomimetic-telemetry --limit 5
```

Telemetry summary:

```text
total_frames=6
last_event=hybrid_recall_trace
candidate_count=24
stage_counts={'graph': 8, 'rerank': 8, 'vector': 8}
raw_text_included=False
```

Visualization smoke:

```powershell
python -m holo_host visualize-biomimetic-system
```

Payload summary:

```text
trajectory_source=biomimetic_telemetry
frame_count=30
recall_microframes=24
html_path=D:\Holo\holo\artifacts\stage100\stage100_biomimetic_system_workbench.html
```

WSL smoke against the current Windows-backed checkout:

```bash
cd /mnt/d/Holo/holo
python3 -m holo_host show-biomimetic-telemetry --limit 2
```

Result summary:

```text
total_frames=7
raw_text_included=False
max_event=hybrid_recall_trace
max_candidate_count=24
stage_counts={'graph': 8, 'rerank': 8, 'vector': 8}
```

## Research Value

Stage102 makes the visualization closer to an empirical instrument:

- Stage101 showed event-level affective-semantic state.
- Stage102 shows within-event recall search movement.
- The workbench can now display a complex network trajectory instead of a single collapsed event dot.

The paper-facing claim remains bounded:

> A redacted event-level and candidate-level telemetry method for visualizing affective-semantic recall dynamics in a continuous LLM-agent runtime.

## Next Work

1. Add explicit ablation tags to telemetry frames: `memory_drop`, `deep_recall_disabled`, `promotion_disabled`.
2. Add schema validation for `holo.biomimetic_frame.v1` and `holo.recall_trajectory.v1`.
3. Add browser screenshot verification for the workbench once Playwright is available.
4. Add a paper-export command that saves payload, HTML, and static PNG panels under a stage-specific artifact directory.

## Boundary

- Telemetry is observational only.
- It does not alter action selection.
- It does not become a second decision layer.
- It does not claim real emotion, consciousness, hidden reasoning, or biological brain state.
