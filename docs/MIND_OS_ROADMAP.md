# Holo Mind OS Roadmap

This repo now tracks the in-place Mind OS refactor.

## Principles
- `memory is the self`
- `processor is replaceable compute`
- `transport is eyes and hands`

## Milestones
1. `M0 Repo + Docs Bootstrap`
   - `.github` templates
   - RFC set
   - release note templates
2. `M1 Memory Substrate`
   - SQLite-backed Mind Graph
   - backfill from archive and JSONL stores
   - helper history file discovery
3. `M2 Retrieval + Mind Packet V3`
   - graph diagnostics
   - recall tracing
   - deep recall cutover
4. `M3 Processor Mesh`
   - task-typed processor interface
   - replay and observability commands
5. `M4 Consciousness Streams`
   - maintenance / association / social / deep-dream scheduling
   - stream audit trail
6. `M5 Social Memory + Autonomy`
   - relationship graph
   - light proactive policy gate
7. `M6 Cutover + Decommission`
   - graph-led retrieval on live reply path
   - legacy JSONL direct-drive retirement

## Current Slice
- Mind Graph substrate exists at `holo_host/mind_graph.py`
- live reply is now graph-led by default, with per-lane legacy fallback
- thread-level incremental graph sync runs after each archived or observed turn
- thread state now carries relationship motifs, unfinished lines, tone tendency, and continuity / trust / closeness scores
- CLI diagnostics exist: `backfill-mind-graph`, `inspect-graph`, `trace-recall`, `show-stream-status`, `show-processor-mesh`, `processor-task`
- Reply API diagnostics exist: `GET /mind-graph`, `GET /trace-recall`, `GET /stream-status`
- Processor mesh foundation exists in `holo_host/codex_runner.py`

## Acceptance Focus
- explicit recall uses `graph-led + deep_recall + recall_reconstruct`
- thread continuity survives `codex_session_id` changes and runtime restarts
- relationship state is not just a summary string; it includes motifs, unfinished lines, tone tendency, and stable scores
- every real turn writes back into archive and incrementally re-materializes the thread graph

## Release Rule
- one merged task => one prerelease note
- one week => one milestone release rollup
