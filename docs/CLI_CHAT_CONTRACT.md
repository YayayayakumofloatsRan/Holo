# Holo CLI Chat Contract

The CLI chat shell is an operator-facing conversation surface for the single
WSL Holo subject. It is not a second brain, a separate user profile, or a
memory-admin console.

## Entry Points

From the WSL repo:

```bash
python3 -m holo_host chat
```

From Windows PowerShell through the shared checkout:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host chat"
```

One-shot smoke test:

```bash
python3 -m holo_host chat --once "你现在状态如何？" --no-local-fallback
```

The default CLI identity is:

```text
channel=holo_cli
thread_key=holo_cli:main
chat_name=HoloCLI
sender=Operator
```

These defaults intentionally keep Holo in one durable CLI thread instead of
creating a new subject context per command invocation.

## Interactive Commands

Inside `python3 -m holo_host chat`:

```text
/help
/status
/readiness
/flow
/mind <query>
/recall <query>
/activation
/snapshot [label]
/json on
/json off
/quit
```

Normal text is sent to `/reply` first. If the live HTTP service is unavailable,
the shell may fall back to an in-process local `HoloReplyService` unless
`--no-local-fallback` is supplied.

When running under WSL, CLI live HTTP discovery tries the configured API port
first and then the standard live Holo port `8004`. This keeps the shared
`/mnt/d/Holo/holo` checkout from silently falling back to a slow in-process
brain when the live subject is running from `/home/holo/holo`.

`holo_cli` is an active-thread fast-lane channel. Short ordinary CLI turns should
use the same Stage17 reflex path as WeChat and mobile Holo instead of forcing
hybrid/deep recall on every command-line exchange. Explicit `/mind` and
`/recall` commands remain available when the operator wants the heavier memory
inspection path.

## Authority Boundary

CLI chat payloads declare:

```text
transport=holo_cli
authority=operator_chat
client_context_policy=single_subject_thread
memory_admin=false
subject_settings=false
```

`reset-memory` is intentionally unavailable inside the interactive shell. Memory
reset remains a separate WSL-only command that requires the exact confirmation
phrase:

```bash
python3 -m holo_host reset-memory \
  --confirm RESET_HOLO_MEMORY_FROM_WSL \
  --reason "operator requested reset"
```

## Auth

When `HOLO_API_BEARER_TOKEN` or the configured token environment variable is
set, CLI live HTTP requests send:

```text
Authorization: Bearer <token>
```

This keeps `chat`, diagnostics, mobile access, and remote access behind the same
HTTP API boundary.
