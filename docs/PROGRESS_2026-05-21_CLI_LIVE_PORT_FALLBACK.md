# Progress - CLI Live Port Fallback - 2026-05-21

## Problem

Launching CLI chat from the shared Windows checkout:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host chat"
```

could miss the live Holo API because the shared checkout defaulted to
`127.0.0.1:8000`, while the running WSL subject was serving the live API on
`0.0.0.0:8004` from `/home/holo/holo`.

When this happened, CLI chat fell back to an in-process local
`HoloReplyService`. That path is slower and can initialize a temporary Milvus
vector backend, which explains the gRPC `too_many_pings` noise seen on exit.

## Fix

`_live_api_base_urls(...)` now treats WSL like Windows for the standard live
port fallback: if the configured port is not `8004`, it tries the configured
port first and then `8004`.

This keeps `/mnt/d/Holo/holo` as a usable operator entrypoint while preserving
the architecture boundary: the live subject remains the WSL brain; the CLI is
only a transport.

## Verification

Focused red-green test:

```powershell
pytest -q tests/test_cli_live_api.py -k wsl_live_request --basetemp .holo_runtime\pytest-tmp
```

Result:

```text
1 passed, 4 deselected
```

Related CLI tests:

```powershell
pytest -q tests/test_cli_live_api.py tests/test_cli_chat.py --basetemp .holo_runtime\pytest-tmp
```

Result:

```text
9 passed
```

Live WSL smoke from the shared checkout:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && timeout 30 python3 -m holo_host chat --once 'ping' --no-local-fallback --timeout 10"
```

Result:

```text
[silence: low_signal_turn_with_low_expression_pressure]
```

This proves the shared-checkout CLI can reach the live API instead of requiring
local fallback.
