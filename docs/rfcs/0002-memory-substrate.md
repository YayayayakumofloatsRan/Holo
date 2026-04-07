# RFC 0002: Memory Substrate

## Status
Accepted

## Decision
The raw ledger remains `conversation_archive.jsonl`, but the operational memory substrate becomes a SQLite-backed Mind Graph.

## Memory Classes
- `sensory_trace`
- `working_memory`
- `episodic_memory`
- `relationship_memory`
- `semantic_self_memory`
- `emotional_trace`
- `dream_residue`
- `initiative_seed`
- `suppressed_conflict`

## Migration Rule
- current JSONL stores remain as compatibility and rollback layers
- Mind Graph is rebuilt from archive, stores, and helper-exported history artifacts
- live reply path may keep using the current structured packet while graph diagnostics mature
