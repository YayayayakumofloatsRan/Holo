# Stage101 Biomimetic Telemetry Spine - 2026-05-21

## Objective

Stage100 made Holo's memory dynamics visible after the fact. Stage101 adds the telemetry spine needed for publishable, replayable biomimetic analysis.

The design target is one redacted frame per observable system event:

- `/reply` through the live HTTP API
- local CLI fallback replies
- `memory-doctor`
- `promote-memory --dry-run` and real promotion
- `visualize-biomimetic-system`

Each frame is a process trace, not a thought transcript.

## Implemented

Added:

- `holo_host/biomimetic_telemetry.py`
- CLI command: `python -m holo_host show-biomimetic-telemetry --limit 25`
- telemetry store: `.holo_runtime/biomimetic_frames.jsonl`
- tests: `tests/test_biomimetic_telemetry.py`

Integrated:

- `reply_api` HTTP `/reply`
- CLI local chat fallback
- `memory-doctor`
- `promote-memory`
- `visualize-biomimetic-system`
- Stage100 visualization now prefers Stage101 telemetry frames when available, then falls back to archive-derived proxy frames.

## Frame Shape

Each `holo.biomimetic_frame.v1` row includes:

- event type and source
- channel/thread/message ids
- input text length and hash only
- action, returned action, route, processor
- timing buckets
- selected-memory count
- activation-trace count
- graph confidence and expression budget
- health status counts
- promotion-plan counts
- semantic-affective proxy vector
- low-dimensional projection
- topology references
- claim-boundary flags

It does not include:

- raw user text
- raw reply text
- bubbles
- prompt text
- memory text
- graph labels

## Verification

Tests:

```powershell
pytest -q tests/test_biomimetic_telemetry.py tests/test_biomimetic_visualization.py tests/test_memory_doctor.py tests/test_memory_promotion.py tests/test_reply_api_auth.py tests/test_cli_chat.py tests/test_memory_admin.py --basetemp .holo_runtime\pytest-tmp
```

Result:

```text
26 passed
```

Windows telemetry smoke:

```powershell
python -m holo_host memory-doctor
python -m holo_host promote-memory --dry-run
python -m holo_host visualize-biomimetic-system
python -m holo_host show-biomimetic-telemetry --limit 6
```

Result summary:

```text
total_frames=3
event_counts={'memory_doctor': 1, 'promotion_plan': 1, 'visualization_export': 1}
raw_text_included=False
```

After regenerating visualization once more:

```text
trajectory.source=biomimetic_telemetry
trajectory.frames=3
last_event_type=visualization_export
```

WSL smoke against the current Windows-backed checkout:

```bash
cd /mnt/d/Holo/holo
python3 -m holo_host show-biomimetic-telemetry --limit 3
```

Result summary:

```text
total_frames=4
raw_text_included=False
returned_frames=3
```

The default WSL user path on this machine was checked as a separate user-home checkout. That checkout was dirty, had many pre-existing uncommitted changes, and was missing Stage100/101 files, so Stage101 did not overwrite it blindly.

## Publication Value

Stage101 changes the project from "visualizes old logs" to "collects a replayable event-level biomimetic trace." This is the difference between an illustration and an empirical instrument.

The publishable unit is now:

> A redacted event-level telemetry schema for continuous affective-semantic memory dynamics in an LLM-agent runtime.

## Next Work

1. Record telemetry from `inspect-mind` and `trace-hybrid-recall` so visualization can show recall search movement before a reply.
2. Add PNG/paper export for Stage100 panels.
3. Add ablation tags to telemetry frames: memory-drop, deep-recall-disabled, promotion-disabled.
4. Add schema validation for `holo.biomimetic_frame.v1`.
5. Add browser-level canvas verification once Playwright is available.

## Boundary

- Telemetry is append-only observational data.
- It does not change action selection.
- It does not become a second decision layer.
- It reports observable proxies only.
- It does not claim real emotion, consciousness, hidden reasoning, or biological brain state.
