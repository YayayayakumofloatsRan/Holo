# Holo MindOS Stage-3: Reflective Subject Kernel

Stage-3 promotes Holo from an always-on companion runtime into a bounded reflective subject kernel.

## Core Shape
- `self_model_state` is now a first-class persisted state alongside thread, game, and stream state.
- `codex exec` is treated as a high-level cortical operator, not as Holo's identity.
- `full_brain` is the default online mode.
- self-modification is split:
  - `mind/state` patches may auto-apply after bounded shadow review
  - repo code changes are shadow-only and must not hot-edit the live working tree
- images are ingested as `visual_memory`, not just sidecar text.

## Runtime Loops
Stage-3 adds these loops to the daemon runtime:
- `self_model_refresh`
- `homeostasis_tick`
- `operator_planning`
- `operator_shadow_cycle`
- `visual_ingest_cycle`

They are observable through:
- `python3 -m holo_host show-brain-status`
- `GET /brain-status`

## New State Surfaces
- `self_model`
  Carries identity continuity, deficits, long-horizon goals, relational commitments, and homeostasis targets.
- `homeostasis_state`
  Tracks pressure, stability, deficits, operator backlog, and active mode.
- `operator_state`
  Tracks pending bounded operator work and the latest reviewed/applied run.
- `visual_memory`
  Tracks scene summary, objects, OCR, mood imagery, thread relevance, and visual anchors.

## Operator Bus
The operator bus gives Holo bounded WSL-side tool use:
- read repo/config/test context
- plan bounded self-fix work
- execute only in a shadow workspace
- review results before any state-layer patch is applied

Runtime writes are forbidden for:
- live repo tracked files
- canonical persona files
- policy/safety boundaries
- secrets and transport auth

Useful commands:
- `python3 -m holo_host operator-probe --thread-key TestUser --chat-name TestUser`
- `python3 -m holo_host run-operator-cycle --thread-key TestUser --chat-name TestUser`

## Visual Memory
Single small images can be synchronously understood on the reply path. Larger or multiple images are queued for async ingest.

Useful commands:
- `python3 -m holo_host ingest-image --path /path/to/image.png --note "苹果和酒摆在木桌上" --thread-key TestUser --chat-name TestUser`
- `python3 -m holo_host trace-visual-recall --thread-key TestUser --chat-name TestUser --query "苹果 酒 木桌"`

## Acceptance Gate
Stage-3 closes with one fixed gate:
- `python3 -m holo_host accept-stage3 --thread-key TestUser --chat-name TestUser --channel wechat`

The gate checks:
- self-model continuity
- bounded operator execution
- visual-memory ingest and recall
- background continuity visibility
- Stage-2 reply latency budgets

Once `accept-stage3` passes, Stage-3 is considered sealed; stronger autonomy and deeper self-edit loops move to Stage-4.
