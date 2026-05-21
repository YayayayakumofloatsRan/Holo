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
