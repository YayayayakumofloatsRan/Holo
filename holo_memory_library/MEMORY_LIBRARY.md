# Local Memory Library

This library is the local memory substrate for a configurable subject runtime. It stores lifecycle memories, archive material, and derived state used by the host runtime, while keeping deployment-specific voice and identity files outside the public repository.

## Public And Private Files
- Public templates: `.subject.example.md`, `subject_seed.example.md`, `voice_profile.example.md`.
- Private local profile files: `.subject.local.md`, `subject_seed.md`, `voice_profile.md`.
- Private live memory stores: `memories/*.jsonl`.
- Private runtime state: `.holo_runtime/`, SQLite databases, transport receipts, snapshots, and canary artifacts.

Real deployments copy the templates to the private filenames and fill in the local subject profile. Those private files are ignored by Git and must not be published.

## Memory Layers
- `canonical`: local subject profile and non-negotiable boundaries.
- `durable`: reviewed long-term memories eligible for prompt retrieval.
- `candidate`: synthesized memories awaiting review.
- `working`: recent observations and temporary notes.
- `archive`: full turn ledger for replay, inspection, and private recovery.

## Retrieval Policy
- Use compact, reviewed memory before raw archive history.
- Preserve same-thread relevance before cross-thread recall.
- Candidate and working memory must not enter prompts raw.
- Drift signals are audit evidence, not prompt-facing truth.
- Explicit memory/history requests should use escalation paths rather than silent archive injection.

## Operational Commands
- Add a structured memory: `python3 rag_memory.py add --kind preference --status durable --text "..."`
- Consolidate an observation: `python3 rag_memory.py consolidate --text "..." --dry-run`
- Observe a turn: `python3 rag_memory.py observe-turn --user "..." --reply "..." --dry-run`
- Archive a turn: `python3 rag_memory.py archive-turn --user "..." --reply "..."`
- Inspect archive: `python3 rag_memory.py show-archive --limit 8`
- Export a private snapshot: `python3 rag_memory.py export-snapshot --label local-backup`
- Restore a private snapshot: `python3 rag_memory.py import-snapshot --path .holo_runtime/snapshots/...json --dry-run`

## Publish Rule
Public releases must pass `python scripts/check_public_release_hygiene.py`. That check blocks tracked private profile files, live memory JSONL, runtime state, local transport config, and artifact exports.
