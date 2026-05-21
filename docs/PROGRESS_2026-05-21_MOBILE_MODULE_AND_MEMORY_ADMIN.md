# Progress - Mobile Module And Memory Admin - 2026-05-21

## Context

The mobile client should keep the original DeepSeek shell intact while adding
Holo as a module. Holo memory reset must be a system-level WSL action only.

## Decisions

- Keep DeepSeek shell behavior additive and default-preserving.
- Holo mobile access remains transport-only:
  - fixed `channel=holo_app`
  - fixed `thread_key=holo_app:HoloSubject`
  - latest user turn only
  - no memory reset or subject settings authority
- Memory reset is CLI-only and WSL-only.
- No `/reset-memory` or `/memory-reset` HTTP endpoint is added.
- Remote/mobile access beyond local USB should set `HOLO_API_BEARER_TOKEN`;
  the HTTP API then requires `Authorization: Bearer ...` for every endpoint.
- Holo now has an operator CLI chat surface, but it remains a transport and
  diagnostic shell for the same WSL subject rather than a second decision layer.

## Holo Runtime Changes

- Added `holo_host.memory_admin`.
- Added CLI command:
  - `python3 -m holo_host reset-memory --confirm RESET_HOLO_MEMORY_FROM_WSL --reason "..."`
- Added CLI chat command:
  - `python3 -m holo_host chat`
  - `python3 -m holo_host chat --once "你现在状态如何？" --no-local-fallback`
- CLI chat supports `/status`, `/readiness`, `/flow`, `/mind`, `/recall`,
  `/activation`, `/snapshot`, and `/json`; reset remains outside the shell.
- `holo_cli` now participates in the Stage17 active-thread fast lane, so short
  operator turns avoid accidental hybrid/deep recall stalls.
- CLI live HTTP calls now send `Authorization: Bearer ...` when the configured
  API bearer token environment variable is set.
- Reset snapshots live memory stores and derived indexes before clearing them.
- Dry-run reset is now non-mutating and reports the affected stores without
  writing backup files.
- Legacy malformed self-revision patches are sanitized on read, so a bad
  `persona_blend` payload cannot kill the daemon loop.
- Added `docs/MEMORY_ADMIN_CONTRACT.md`.
- Added `docs/REMOTE_ACCESS_CONTRACT.md`.
- Added `docs/CLI_CHAT_CONTRACT.md`.
- Added `scripts/holo-cloudflare-quick-tunnel.ps1` for token-gated
  cross-network testing through Cloudflare Quick Tunnel.

## Verification

- `python -m pytest tests\test_memory_admin.py -q --basetemp .pytest_tmp\memory_admin`: 5 passed.
- `python -m pytest tests\test_cli_live_api.py tests\test_memory_admin.py -q --basetemp .pytest_tmp\memory_admin_cli`: 7 passed.
- `python -m pytest tests\test_stage2_brain.py tests\test_memory_admin.py tests\test_cli_live_api.py -q --basetemp .pytest_tmp\brain_memory_admin`: 13 passed.
- `python -m pytest tests\test_holo_host.py tests\test_memory_fabric.py -q --basetemp .pytest_tmp\host_memory_fabric`: 77 passed.
- `python -m pytest tests\test_reply_api_auth.py tests\test_memory_admin.py tests\test_stage2_brain.py -q --basetemp .pytest_tmp\remote_auth`: 13 passed.
- `python -m pytest tests\test_cli_chat.py tests\test_cli_live_api.py -q --basetemp .pytest_tmp\cli_chat_live`: 7 passed.
- `python -m pytest tests\test_cli_chat.py tests\test_cli_live_api.py tests\test_reply_api_auth.py tests\test_memory_admin.py -q --basetemp .pytest_tmp\cli_chat_auth_memory`: 14 passed.
- `python -m pytest tests\test_stage2_brain.py tests\test_holo_host.py tests\test_memory_fabric.py tests\test_cli_chat.py tests\test_cli_live_api.py -q --basetemp .pytest_tmp\cli_chat_regression`: 90 passed.
- `python -m pytest tests\test_stage17_realtime_runtime.py tests\test_stage18_dual_speed_reflex.py tests\test_stage2_brain.py tests\test_holo_host.py tests\test_memory_fabric.py tests\test_cli_chat.py tests\test_cli_live_api.py tests\test_reply_api_auth.py tests\test_memory_admin.py -q --basetemp .pytest_tmp\cli_chat_fast_full`: 110 passed.
- `python -m py_compile holo_host\brain_ops.py holo_host\mind_graph.py holo_host\memory_bridge.py holo_host\operator_bus.py holo_host\memory_admin.py`
- `python -m py_compile holo_host\reply_api.py holo_host\config.py`
- `python -m py_compile holo_host\cli.py holo_host\reply_api.py holo_host\memory_admin.py`
- `python -m py_compile holo_host\cli.py holo_host\reply_api.py holo_host\memory_admin.py holo_host\memory_bridge.py holo_host\mind_graph.py`
- WSL `reply_api` and `daemon` restarted without WeChat transport; `/health`
  returned `ok` and `/live-readiness` returned `ready`.
- After remote-auth sync, WSL `/health` returned `ok` with
  `auth_required=false` when no bearer token is set.
- A mobile-shaped `/reply` payload on `channel=holo_app` returned
  `reply_loop_outcome=clean_pass`.
- After CLI fast-lane sync and WSL API/daemon restart, WSL
  `/live-readiness` returned `ready`.
- WSL live CLI smoke:
  - `python3 -m holo_host chat --once 'ping' --no-local-fallback --timeout 45`
    returned a valid semantic `silence` action instead of a transport error.
  - `python3 -m holo_host chat --once '你在线吗？用一句话回答。' --no-local-fallback --timeout 60`
    returned a live reply through `/reply`.
