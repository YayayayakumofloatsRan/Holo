# Memory Admin Contract

Holo memory is subject state. It is not a mobile-app preference, a transport
setting, or a per-client cache.

## Authority Boundary

- WSL is the only authority allowed to reset Holo memory.
- Mobile apps, WeChat transport, Windows helper processes, and HTTP endpoints
  must not expose memory reset or subject-setting controls.
- All media and clients remain perception/transport surfaces. They may provide
  turns, artifacts, and context, but the WSL subject kernel decides how to
  interpret them.

## Reset Entry Point

Use only from the WSL repo:

```bash
python3 -m holo_host reset-memory \
  --confirm RESET_HOLO_MEMORY_FROM_WSL \
  --reason "operator requested reset"
```

For inspection:

```bash
python3 -m holo_host reset-memory \
  --confirm RESET_HOLO_MEMORY_FROM_WSL \
  --reason "operator dry run" \
  --dry-run
```

The command refuses to run outside WSL.

## Reset Semantics

Before clearing, the command writes a reset snapshot under:

```text
.holo_runtime/memory_resets/<timestamp>/
```

It snapshots and clears the JSONL memory stores under
`holo_memory_library/memories/`, then removes derived runtime memory indexes
such as the Mind Graph SQLite database, Milvus-lite vector store, and visual
ingest queue.

It does not modify `.holo_host.toml`, provider configuration, startup scripts,
mobile application state, or transport configuration.

## Mobile Rule

The mobile Holo module may send user turns to `/reply` with fixed
`channel=holo_app` and `thread_key=holo_app:HoloSubject`. It must not call or
offer reset, restore, or subject-setting controls. Continuity belongs to the
WSL Holo runtime, not to the phone.

## Kernel v3 Inspection

Kernel v3 exposes a read-only durable-memory health surface for resident-agent
operation:

```bash
holo-v3 --memory-log .state/kernel_v3/memory.jsonl memory inspect
```

The command reports active, expired, deleted, sensitive, pending-proposal,
shadow-candidate, tombstone, and audit-record counts, plus small safe samples
and recommended operator actions. It does not approve proposals, commit memory,
delete memory, or expose raw secret-like rejected payloads.

When a journal and artifact store are configured, the same inspection also
checks committed memory references without reading raw artifact payloads:
provenance refs must point at existing journal records, and artifact refs must
still have artifact metadata and blob payloads. Missing refs are reported as
inspection issues with bounded samples and repair recommendations.

The same surface is available in thread chat:

```text
/memory inspect
```

This lets a resident worker or operator see whether memory needs review without
making transports decision makers. Approval, rejection, delete, and export still
go through explicit host-owned memory commands.

Approval, rejection, commit, and delete are durable state transitions and must
be visible in the main journal. Kernel-v3 memory delete goes through
`MemoryPipeline.delete_memory`, which writes the memory-store tombstone and
journals either `memory_item_deleted` for the first deletion or
`memory_item_delete_observed` for an idempotent repeat. The journal record
contains ids, reason, provenance refs, and metadata, not raw artifact payloads.
Unknown proposal or memory ids are command failures, not resident worker
failures: chat journals a failed `chat_command`, the CLI journals
`memory_command_failed`, and resident inbox processing completes with a failed
outbox instead of retrying or dead-lettering a bad admin command.

The durable store treats `commit` as the final boundary, not a proposal API:
only active items with a non-empty `approved_by` value may be committed. Pending
or unapproved drafts must stay in the proposal/shadow pipeline until the host
approves or rejects them.

Context injection uses a run/resume snapshot of recallable memory only: deleted
and expired items are excluded, and `sensitive` memory is withheld unless the
compiler is explicitly configured with `include_sensitive_memory=True`.
Each durable-memory context injection records a safe `memory_items_recalled`
event in the memory store and updates `last_accessed_ms` for the recalled
items. The access record contains memory ids, scope, filter counts, and context
ids; it does not contain raw artifact payloads or raw task bodies. Access
auditing is metadata only: it does not approve proposals, commit new memories,
or let the model write durable state. `memory export <memory_id>` includes
these recall/access events for the selected item, and memory inspection samples
surface `last_accessed_ms` so an operator can see whether durable memory is
actually being used.

Chat memory admin commands journal preview/manifest payloads only. They may
show memory ids, summaries, proposal status, counts, provenance refs, and
redaction metadata, but they do not copy durable memory bodies, structured
fields, or full export payloads into `chat_command` records. Use the explicit
CLI/store export surface for a full item export.

For long-running resident operation, `holo-v3 resident doctor` aggregates the
read-only memory inspection with resident queue, schedule, and configured
research-corpus inspections. The doctor report is an operator snapshot only: it
does not approve proposals, write durable memory, enqueue work, retrieve
documents, or execute tools. If memory and artifact stores are configured, the
doctor report includes the same memory provenance/artifact consistency check.
