# Stage17 Thread-Resident Realtime Runtime

## Goal

Stage17 moves ordinary short WeChat turns from reconstruction-heavy context building to thread-resident active state. Holo should feel like it is carrying the live thread forward instead of rereading recent chat history for every small turn.

## Boundary

- No second brain layer.
- No new consciousness feature surface.
- No new always-on heavy loop.
- No operator safety weakening and no live repo hot edits.
- Preserve memory-is-self, processor-replaceable, transport-eyes-hands, canonical `wechat:<name>` identity, and action-market-first deliberation.

## What Changed

- `ActiveThreadState` is an internal MindGraph runtime state keyed by `channel + canonical thread_key`.
- Ingress updates ActiveThreadState with bounded O(1) fields: continuity summary, latest user intent, last outbound action, unresolved references, affect hint, relationship tension, tempo, attention focus, cache warmth, and recent turn ids.
- Ordinary short WeChat turns can now use an `active-thread-fast` memory route before graph/vector hybrid recall is invoked.
- Fast-lane prompts prefer continuity summary and last outbound action over verbatim recent-history windows.
- Recall escalation no longer treats low confidence alone as enough for deep recall; escalation requires explicit memory/history need, unresolved reference, high-risk continuity ambiguity, factual recall need, or cold active state.
- Active WeChat history refresh is no longer blocking for ordinary short turns. It remains available for explicit history/memory requests or hard continuity failures.

## Expected Data Contract

- `mind_graph.active_thread_state` persists one row per `channel + thread_key`.
- `mind_packet.active_thread_state` exposes the current active thread snapshot to the subject kernel.
- `mind_packet.stage17` records `fast_lane`, `recall_escalation_reason`, `history_policy`, and `max_fast_history_lines`.
- Fast-lane prompt rendering records `history_lines_in_prompt` in turn metadata and keeps it at `0-1` for ordinary active-thread turns.

## Acceptance Checklist

- `python -m holo_host --config .holo_host.example.toml accept-stage17 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `python -m holo_host --config .holo_host.example.toml accept-stage14`
- `python -m holo_host --config .holo_host.example.toml accept-stage16`
- `pytest -q`

`accept-stage17` checks active state visibility, active fast-lane routing, prompt history minimization, explicit memory-query escalation, nonblocking ordinary history refresh, action-market-first continuity, and Stage14 replay health.

## Rollback

Stage17 only adds internal state and read-only acceptance. If online shadow testing regresses, disable the active fast lane by reverting the Stage17 patch; existing graph, archive, processor fabric, and transport contracts do not require migration.
