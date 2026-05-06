# WeChat Watcher Interface Contract

This document is the hard contract for the Windows-side WeChat watcher path.

If a later thread needs to touch the live WeChat transport, read this file before editing `windows_helper/` or `holo_host/reply_api.py`.

The goal is simple:

- Windows does eyes and hands.
- WSL does memory, deliberation, and reply policy.
- The watcher is a thin transport shell, not a second brain.

## 1. Topology

Authoritative live shape on this machine:

- live kernel: WSL repo at `/home/holo/holo`
- Windows helper repo mirror: `D:\Holo\holo`
- live transport mode: `pyweixin_dialog`
- live agent endpoint: WSL reply API, usually `http://<wsl-ip>:8004`

The watcher must never become a second decision-maker. Its only job is:

1. observe WeChat UI
2. package turns and artifacts
3. call the reply API
4. send already-decided replies
5. write heartbeat and receipts

## 2. Source Of Truth Files

There are two config layers. Do not confuse them.

Static source config:

- `D:\Holo\holo\windows_helper\wechat_helper.live.json`

Generated runtime config:

- `D:\Holo\holo\.holo_runtime\wechat-helper\wechat_helper.runtime.json`

Rules:

- edit `wechat_helper.live.json`
- do not hand-edit `wechat_helper.runtime.json` except one-off debugging
- `start_holo_wechat.ps1` owns generation of the runtime config
- the runtime config may rewrite `agent_url` from `127.0.0.1` to the current WSL IP

Runtime state files:

- `D:\Holo\holo\.holo_runtime\wechat-helper\transport_state.live.json`
- `D:\Holo\holo\.holo_runtime\wechat-helper\state.live.json`
- `D:\Holo\holo\.holo_runtime\wechat-helper\receipts\pyweixin_watcher.log`
- `D:\Holo\holo\.holo_runtime\wechat-helper\send_queue\`
- `D:\Holo\holo\.holo_runtime\wechat-helper\sent\`
- `D:\Holo\holo\.holo_runtime\wechat-helper\failed\`

## 3. Process Contract

Start path:

- `D:\Holo\holo\windows_helper\start_holo_wechat.ps1`

Stop path:

- `D:\Holo\holo\windows_helper\stop_holo_wechat.ps1`
- `D:\Holo\holo\windows_helper\kill_watchers.ps1`

`start_holo_wechat.ps1` is not optional glue. It does required live work:

- kills stale watcher/sender processes
- loads `wechat_helper.live.json`
- rewrites `agent_url` to the active WSL IP when `HOLO_WSL_DISTRO` is set
- writes `wechat_helper.runtime.json`
- starts:
  - `weixin_sender.pyw`
  - `pyweixin_watcher.pyw`

Do not start `pyweixin_watcher.pyw` directly for normal live use unless you are intentionally bypassing runtime config generation for a diagnostic.

## 4. Live Transport Mode Contract

On this machine, the intended online mode is:

- `watch_mode = "pyweixin_dialog"`

This is a hard operational default, not a casual preference.

Do not switch to:

- `pyweixin`
- `wcf`
- `auto`

unless all of the following are true:

- you have a concrete compatibility reason
- you run targeted tests
- you run live smoke checks
- you update docs and handoff notes

Current reason for this rule:

- `wcferry 39.x` is not the intended pairing for local `Weixin 4.1.x`
- `pyweixin_dialog` is the only stable online lane currently accepted here

## 5. Watcher -> Reply API Contract

The live watcher uses a small API surface.

Used by the live chain:

- `POST /reply`
- `POST /ingest-artifact`

Used for diagnostics or helper tooling:

- `GET /health`
- `POST /snapshot`
- `POST /restore-snapshot`
- `GET /revive-packet`

### 5.1 /reply request contract

The watcher sends one normalized `ChatTurn` payload.

The watcher does not decide whether to answer.

The reply API returns a structured decision such as:

- `action = "reply"`
- `action = "silence"`
- `action = "defer_reply"`
- `action = "ignore"`

If `action != "reply"`, the watcher must not manufacture text on its own.

Stage22 keeps canary policy host-side. In default `shadow` mode, `/reply` may return `action = "silence"` with `stage22_shadow = true` and `stage22` trace metadata after the host has selected the would-have action. The watcher must treat that exactly like any other non-reply response and must not send.

If `action == "reply"`, the payload may include:

- `text`
- `bubbles`
- `cadence_ms`

The watcher may send bubbles, but it must not re-split or expand them beyond what the host already decided.

### 5.2 /ingest-artifact request contract

The watcher uses `POST /ingest-artifact` for:

- history export markdown
- live captures
- image/file row captures

The payload includes:

- `path`
- `note`
- `tags`
- `source`
- `dry_run`
- optional Stage22 bounded world-cue fields:
  - `channel`
  - `thread_key`
  - `chat_name`
  - `world_cue_type`: `file_artifact`, `image_summary`, `schedule_cue`, or `task_cue`
  - `due_at`

The host must accept Windows-origin artifact paths from the helper.

Stage22 world-cue fields are perception inputs only. They do not let the watcher decide, schedule, recall, or send.

## 6. Artifact Path Normalization Contract

This path handling is high-risk and must be changed carefully.

The host must support all of these forms:

- normal Windows absolute path
  - `D:\Holo\holo\.holo_runtime\wechat-helper\receipts\history_exports\foo.md`
- normal WSL mount path
  - `/mnt/d/Holo/holo/.holo_runtime/wechat-helper/receipts/history_exports/foo.md`
- malformed historical path seen in old breakages
  - `D:\mnt\d\Holo\holo\.holo_runtime\wechat-helper\receipts\history_exports\foo.md`

Why this matters:

- the helper is Windows-native
- the host may be read from WSL or Windows contexts
- old broken normalization created fake paths like `D:\mnt\d\...`
- if this breaks, history export ingestion fails and recall depth silently collapses

Code touching this contract:

- `D:\Holo\holo\holo_host\reply_api.py`

Tests covering this contract:

- `tests.test_holo_host.test_coerce_helper_artifact_path_repairs_malformed_windows_prefixed_mnt_path`
- `tests.test_holo_host.test_reply_service_normalizes_windows_artifact_path_for_wsl`

## 7. AgentClient Fallback Contract

`windows_helper/wechat_helper.py` defines `AgentClient`.

Important rule:

- `_candidate_base_urls()` must exist and remain reachable from `_execute()`

Purpose:

- allow the helper to try the current configured `agent_url`
- on Windows, if that host is `127.0.0.1` or `localhost`, allow fallback to the current WSL IP

If this method disappears or is moved incorrectly, the watcher may hard-crash with:

- `AttributeError: 'AgentClient' object has no attribute '_candidate_base_urls'`

That exact failure has already happened and should be treated as a known regression shape.

## 8. Transport State Contract

`transport_state.live.json` is used by operations and status checks.

Do not casually rename or delete these fields:

- `status`
- `mode`
- `transport`
- `watch_mode`
- `heartbeat_at`
- `detail`
- `error_type`

`scripts/holo-status.sh` depends on this file shape staying stable enough to report live transport health.

## 9. Safe Change Checklist

Before changing the watcher path:

1. read this file
2. read `windows_helper/README.md`
3. stop the watcher
4. make the smallest possible change
5. run targeted tests
6. restart the watcher through `start_holo_wechat.ps1`
7. verify heartbeat and logs
8. update docs if any runtime contract changed

## 10. Minimum Regression Tests

Run these before calling the watcher path fixed:

```powershell
python -m unittest D:\Holo\holo\tests\test_holo_host.py -k coerce_helper_artifact_path
python -m unittest D:\Holo\holo\tests\test_holo_host.py -k reply_service_normalizes_windows_artifact_path_for_wsl
python -m unittest D:\Holo\holo\tests\test_windows_helper.py -k watch_live_dispatches_pyweixin_dialog_mode
```

## 11. Live Smoke Checks

After restart, verify all of these:

```powershell
Get-Content D:\Holo\holo\.holo_runtime\wechat-helper\wechat_helper.runtime.json
Get-Content D:\Holo\holo\.holo_runtime\wechat-helper\transport_state.live.json
Get-Content D:\Holo\holo\.holo_runtime\wechat-helper\receipts\pyweixin_watcher.log -Tail 40
wsl -d HoloUbuntu -- bash -lc "cd /home/holo/holo && ./scripts/holo-status.sh | sed -n '1,6p'"
```

Expected live signals:

- runtime config `watch_mode = pyweixin_dialog`
- runtime config `agent_url = http://<wsl-ip>:8004`
- transport state says `status=online`, `mode=live`, `transport=pyweixin_dialog`
- `heartbeat_age_s` stays fresh in `holo-status.sh`
- watcher log has no new crash trace after the latest start line

## 12. High-Risk Changes

Treat these as contract changes, not refactors:

- changing `watch_mode` defaults
- changing watcher start/stop scripts
- changing runtime config generation
- changing `AgentClient` fallback behavior
- changing `/reply` response semantics expected by the watcher
- changing `/ingest-artifact` path semantics
- moving Stage22 canary decisions out of the host
- moving `.holo_runtime\wechat-helper\` paths

If any of those change, update:

- this contract
- `windows_helper/README.md`
- `HOLO_HANDOFF.md`

## 13. One-Line Rule

If the helper can no longer be described as "Windows captures and sends, WSL decides," the watcher path has drifted too far.
