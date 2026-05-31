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

The same surface is available in thread chat:

```text
/memory inspect
```

This lets a resident worker or operator see whether memory needs review without
making transports decision makers. Approval, rejection, delete, and export still
go through explicit host-owned memory commands.

For long-running resident operation, `holo-v3 resident doctor` aggregates the
read-only memory inspection with resident queue, schedule, and configured
research-corpus inspections. The doctor report is an operator snapshot only: it
does not approve proposals, write durable memory, enqueue work, retrieve
documents, or execute tools.
