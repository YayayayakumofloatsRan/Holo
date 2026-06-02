# Kernel v3 Storage Layout

Kernel v3 uses separate storage surfaces for audit, thread UX, durable memory,
artifacts, and resident queues. The goal is to keep the host-owned audit trail
complete while keeping user-facing thread history readable.

## Default Root

Default root:

```text
.state/kernel_v3/
```

Override:

```bash
HOLO_V3_STATE_DIR=/path/to/state holo-v3 chat
```

## Surfaces

```text
.state/kernel_v3/
  journal/
    global.jsonl
    global.sqlite
  threads/
    <thread_id>/
      thread.jsonl
  memory/
    memory.jsonl
    memory.sqlite
```

`journal/global.jsonl` is the complete execution ledger. It may contain model
processor records, policy decisions, tool actions, retrieval attempts, evidence,
citations, observations, chat events, and final results. It is intentionally
append-only and audit-oriented.

`threads/<thread_id>/thread.jsonl` is a user-facing transcript mirror. It stores
chat turns, routing decisions, commands, assistant results, and thread summaries.
It does not replace the global journal and does not carry raw fetched bodies or
full tool payload blobs.

`memory/memory.jsonl` and `memory/memory.sqlite` are the durable-memory event log
and index. The model can propose memory, but only host-side memory pipeline code
can approve, reject, commit, delete, or export durable memory. A configured empty
memory index does not mean Holo has remembered anything.

## Legacy Files

Legacy files such as `kernel_v3/.holo-v3-journal.jsonl` and
`kernel_v3/.holo-v3-journal.sqlite` are old single-ledger state files. They are
not automatically deleted. If needed, treat them as migration input. New CLI
sessions should use `.state/kernel_v3` unless `--journal`, `--index`, or
`HOLO_V3_STATE_DIR` explicitly point somewhere else.

## Operational Rule

Do not use per-thread transcripts as the source of truth for tool execution,
policy validation, evidence, citations, or workloop termination. The transcript
is for interaction continuity and inspection. The journal remains the audit
source of truth.
