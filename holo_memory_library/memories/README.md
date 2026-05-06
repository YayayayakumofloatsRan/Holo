# Structured Memory Stores

This directory is the private live-memory location for local deployments.

The public repository tracks only this README. Runtime JSONL stores are ignored by Git:
- `working_store.jsonl`
- `candidate_store.jsonl`
- `memory_store.jsonl`
- `emotion_trace.jsonl`
- `conversation_archive.jsonl`
- `callback_candidates.jsonl`
- `thought_stream.jsonl`
- `initiative_candidates.jsonl`

## Store Roles
- `working`: raw observations and temporary notes.
- `candidate`: synthesized memories awaiting review.
- `durable`: reviewed long-term memories eligible for retrieval.
- `emotion_trace`: short-range stance and affect carry-over.
- `conversation_archive`: full private turn ledger for replay and recovery.
- `callback_candidates`: replay-produced revisit candidates that still require policy gates before any outbound action.

## Publish Boundary
Do not commit JSONL stores, chat exports, snapshots, transport receipts, or private profile material. Public examples should use placeholders, not real contacts, real thread keys, or personal conversation excerpts.
