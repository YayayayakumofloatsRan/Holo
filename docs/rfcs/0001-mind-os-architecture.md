# RFC 0001: Mind OS Architecture

## Status
Accepted

## Decision
Holo is refactored in place into a Mind OS with three permanent truths:
- memory is the self
- processor is replaceable compute
- transport is eyes and hands

The runtime shape is:
- Archive ledger
- Mind Graph
- Semantic field carried by structured packets
- Active streams
- Processor mesh

## Consequences
- `codex_session_id` is compute cache only
- live continuity must survive processor swaps, session loss, and restarts
- diagnostics must show retrieval and stream state without dumping internals into user-facing replies
