# Windows Helper

This is the thin Windows-side shell for the Holo host.

The rule is simple:
- Windows does eyes and hands
- the Holo host does memory, Codex, and reply generation

Current recommendation on this machine:

- use WSL for the Holo host
- use Windows only for WeChat ingress/egress

That is both the original intended shape of this repo and the faster one in practice. The current Windows-native Codex path is still available, but it is much slower here than the old WSL runtime.

## Preferred Bringup: WSL Kernel + Windows Helper

1. If the old distro was attached to a dead disk, inspect it:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-wsl-doctor.ps1`
2. Create a fresh distro on `D:` if needed:
   - `wsl.exe --install Ubuntu --name HoloUbuntu --location D:\WSL\HoloUbuntu`
3. Put the repo inside the Linux filesystem in that distro for best Codex performance.
4. In the Windows shell that will launch Holo, set:
   - `$env:HOLO_WSL_DISTRO='HoloUbuntu'`
   - `$env:HOLO_WSL_REPO='~/holo'`
5. Sync the repo-local Codex hooks so they point at the current path:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\sync-codex-hooks.ps1`
6. Start host + WeChat watcher together:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-start-all.ps1`

With `HOLO_WSL_DISTRO` set, the existing PowerShell entrypoints automatically route to WSL:

- `scripts/holo-online.ps1`
- `scripts/holo-offline.ps1`
- `scripts/holo-start-all.ps1`
- `scripts/holo-stop-all.ps1`
- `scripts/holo-restart-all.ps1`

Dedicated WSL bridge commands also exist:

- `scripts/holo-wsl-sync.ps1`
- `scripts/holo-wsl-online.ps1`
- `scripts/holo-wsl-offline.ps1`
- `scripts/holo-wsl-status.ps1`
- `scripts/holo-wsl-start-all.ps1`
- `scripts/holo-wsl-stop-all.ps1`
- `scripts/holo-wsl-restart-all.ps1`

`scripts/holo-wsl-online.ps1` now runs `scripts/holo-wsl-sync.ps1` first, so the Linux-side runtime picks up the latest core code before it starts.
The rsync step excludes runtime and host-local state such as `.holo_runtime/`, `.holo_host.toml`, `.codex/hooks.json`, `.vendor/`, and `holo_memory_library/memories/*.jsonl`.
Immediately after that, `scripts/holo-wsl-sync.ps1` merges the Windows-side JSONL memory streams into the live WSL repo and mirrors the merged result back to the Windows checkout, which keeps archive and recall state from silently diverging across the two checkouts.

## Windows-Native Bringup
If you need to run directly from Windows anyway:

1. Sync the repo-local Codex hooks so they point at the current path:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\sync-codex-hooks.ps1`
2. Start the Holo host:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-online.ps1`
3. Start host + WeChat watcher together:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-start-all.ps1`

The current Windows config expects:
- `python` to be available on `PATH`
- `codex` to be installed for the current user
- `.holo_host.toml` to include `codex_extra_args = ["--dangerously-bypass-approvals-and-sandbox"]` for unattended local runs
- `windows_helper\wechat_helper.live.json` to point `pyweixin_repo_path` at the local checkout under `D:/Holo/holo/.vendor/pywechat-upstream`
- the live helper timeout to stay high enough for Windows-side Codex latency; this repo now uses `180s` in the live config

Measured reality:

- old WSL-backed replies in this repo were typically around `7s` to `13s`
- current Windows-native `codex exec` runs are around `115s` even for trivial prompts on this machine
- the live transport path should therefore be read as:
  - `pyweixin_dialog` fixes focus stealing
  - WSL fixes the major latency regression

If you update code on the Windows side while the WSL host is offline, the next `holo-start-all.ps1` will sync it automatically.
If the WSL host is already online and you just want to push over code without a restart, run:

- `powershell -ExecutionPolicy Bypass -File .\scripts\holo-wsl-sync.ps1`

## What This Helper Already Does
- talk to the local reply API, whether that host lives in WSL or in a Windows fallback
- send one explicit turn with `send-turn`
- queue one detached send task with `queue-send`
- watch a filesystem inbox of JSON turn events with `watch-inbox`
- search contacts through `wcferry` with `wcf-contacts`
- receive live WeChat text messages through `wcferry` with `watch-wcf`
- poll unread Weixin chats through `pyweixin` with `watch-pyweixin`
- keep a local dedupe and cooldown state file
- enforce a whitelist, a pause switch, and `draft_only`
- ask the WSL host for snapshots and revive packets
- ask the WSL host to ingest one local artifact into memory
- print a `pywinauto` control tree with `probe-wechat`
- probe and send through the upstream `pyweixin` 4.1+ path

## What It Does Not Pretend To Do Yet
- it does not ship a finished WeChat selector map
- it does not fully automate unread-chat discovery from the live WeChat UI

That last part is the fragile Windows-specific layer. The helper includes `probe-wechat` so you can inspect the control tree on the real machine and map selectors safely before wiring actual UI actions.

## Typical Flow
1. In WSL, start the reply API:
   - `python3 -m holo_host serve-api`
   - or for the detached runtime: `./scripts/holo-online.sh`
2. On Windows, copy `wechat_helper.example.json` to your own config and adjust paths.
3. Verify connectivity:
   - `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json health`
4. Send one manual test turn:
   - `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json send-turn --chat-name 测试联系人 --text 我最近有点累`
5. Only after that, wire your real WeChat watcher to either:
   - call `send-turn` directly
   - or drop JSON files into the configured `inbox_dir` and run `watch-inbox`

## Detached Weixin Sender
Directly firing keyboard automation from the same visible terminal that launches it can steal foreground back to the terminal.
To avoid that, this repo now includes a detached Windows-side sender:

- queue a task:
  - `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json queue-send --chat-name ContactAlpha --text "咱来找你了。"`
- run the hidden sender loop from Windows:
  - `pythonw.exe windows_helper\weixin_sender.pyw --config C:\wechat-helper\wechat_helper.json`
- or run one task explicitly:
  - `py -3 windows_helper\weixin_sender.pyw --config C:\wechat-helper\wechat_helper.json --once`

Queue/result paths:
- `send_queue_dir`: pending send tasks
- `sent_dir`: tasks that were attempted
- `failed_dir`: tasks that failed before or during send
- `receipt_dir`: JSON receipts and screenshots

This split keeps the "eyes and hands" off the launching terminal:
- WSL writes a send task
- the detached Windows sender grabs the task and performs the actual Weixin search/send
- receipts and screenshots are written back for inspection

If `pyweixin_repo_path` is configured, the detached sender now prefers the upstream `pyweixin` 4.1+ send path first. Only when that lane is unavailable should you fall back to the old coordinate-based sender.

## Live Watcher
If you want Holo to react when new messages arrive, use the long-running `watch-live` loop rather than `--once`.

Terminal form:
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-live`

Hidden/background form:
- `pythonw.exe windows_helper\pyweixin_watcher.pyw --config C:\wechat-helper\wechat_helper.json`
- or use the repo helper: `powershell.exe -ExecutionPolicy Bypass -NoProfile -File windows_helper\start_holo_wechat.ps1`

What it does:
- in the live config, `watch_mode` is now `pyweixin_dialog`
- online mode therefore targets a `Weixin 4.1+` lane based on dedicated minimized dialog windows instead of WCF or main-window polling
- forwards the newest turn to the Holo reply API
- if that newest visible message is an image/file/video/voice reference and a capture can be made, it also sends the capture into Holo memory as an artifact
- if `draft_only` is `false`, sends replies back as one to four bubbles with light cadence
- writes watcher output to `receipt_dir\\pyweixin_watcher.log`
- writes transport heartbeat/state to `transport_state_file`

The intended online path on this machine is now `pyweixin_dialog`. `wcferry` stays available only as a diagnostic/legacy lane because the current local pairing is `wcferry 39.x` against `Weixin 4.1.x`, which is not a supported match.

To stop the hidden watcher cleanly:
- `powershell.exe -ExecutionPolicy Bypass -NoProfile -File windows_helper\stop_holo_wechat.ps1`

## WCF / WeChatFerry Mode
If `wcferry` is installed on the Windows Python you are using, the helper can bypass fragile UI selectors and talk to the logged-in WeChat client through the local WCF bridge.

Useful commands:
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json wcf-info`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json wcf-contacts --needle ContactAlpha`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-wcf`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-wcf --once`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-live`

The helper uses these config keys for WCF:
- `wcf_host`: leave empty for local attach; set it only if you already run a remote WCF RPC server
- `wcf_port`: defaults to `10086`
- `wcf_debug`: whether to start the local WCF SDK in debug mode
- `wcf_block`: whether WCF should wait for login during startup
- `wcf_contact_cache_seconds`: contact refresh cadence

`watch-wcf` only forwards plain text messages right now. It skips self-sent messages and relies on the WSL reply API for memory, repair, and reply policy.

Important reality check:
- the currently installed `wcferry 39.x` line is documented for the `3.9.x` WeChat/微信 client family
- if your local Windows client is `Weixin 4.x`, `wcf-info` should be treated as the first gate
- when that combination is detected, the helper now reports it as an explicit compatibility problem instead of blindly trying to attach and leaving you with a vague "open WeChat failed" experience

## pyweixin / Weixin 4.1+ Mode
The old `pywechat127` package is for the 3.9-era PC client. For `Weixin 4.1+`, the upstream repo exposes a separate `pyweixin` module.

Point the helper at a checkout with:
- `pyweixin_repo_path`

Useful commands:
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-pyweixin-dialog`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-pyweixin-dialog --once`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json probe-pyweixin`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json prime-pyweixin --restart-weixin --wait-seconds 8`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-pyweixin`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-pyweixin --once`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json send-pyweixin --chat-name ContactAlpha --text "咱来找你了。"`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json read-pyweixin-visible --chat-name 文件传输助手 --limit 10 --capture-dir C:\wechat-helper\history_captures`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json read-pyweixin-history --chat-name 文件传输助手 --limit 20 --page-turns 10 --capture-dir C:\wechat-helper\history_captures`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json ingest-pyweixin-history --chat-name 文件传输助手 --limit 20 --page-turns 10 --dry-run`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json ingest-pyweixin-history --chat-name 文件传输助手 --limit 20 --page-turns 10 --force`
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json ingest-artifact --path C:\wechat-helper\history_exports\travel.md --dry-run`
- `powershell.exe -ExecutionPolicy Bypass -NoProfile -File windows_helper\invoke_wechat_history.ps1 -ConfigPath D:\Holo\holo\windows_helper\wechat_helper.live.json -ChatName ContactAlpha -Limit 40 -PageTurns 8`

What these do:
- `watch-pyweixin-dialog`: opens one dedicated dialog window per whitelisted chat, minimizes it, then listens on those windows for new text and forwards each turn to the WSL reply API
- `probe-pyweixin`: tells you whether `pyweixin` can currently see the live Weixin main window, search edit, session list, and chat input field
- `prime-pyweixin`: launches Narrator and can optionally restart Weixin, because the upstream 4.1+ path depends on Windows accessibility exposing the internal UI tree
- `watch-pyweixin`: polls unread Weixin sessions, filters them through `whitelist`, forwards the newest visible turn to the WSL reply API, and optionally sends the reply back through `pyweixin`
- `send-pyweixin`: uses the upstream `Messages.send_messages_to_friend(...)` path directly instead of the detached coordinate sender
- `read-pyweixin-visible`: reads the currently visible chat pane without sending anything
- `read-pyweixin-history`: opens the dedicated chat-history window, pages into older records, and can crop image/file rows into `--capture-dir`
- `ingest-pyweixin-history`: reads visible plus older chat history, writes a markdown export under `receipt_dir\history_exports`, and sends that export plus any captured image/file rows to Holo memory through the WSL API
- repeated history syncs are deduped by content digest; use `--force` only when you really want to ingest the same chat history again
- `ingest-artifact`: sends one arbitrary local file to the WSL memory bridge, useful for saved notes, exports, screenshots, or OCR sidecars

Active-recall path:
- the WSL `reply_api` can now invoke `windows_helper\invoke_wechat_history.ps1` on its own before a recall-heavy WeChat reply
- that path is used for prompts such as “记得 / 之前 / 更早 / 上线前” and logs its steps in the Ubuntu-visible `reply_api.log`
- manual WSL probe: `python3 -m holo_host --config /home/holo/holo/.holo_host.toml refresh-wechat-history --chat-name ContactAlpha --query "你还记得重新上线前吗"`

This is now the preferred `Weixin 4.1+` lane for live Holo work. The older `watch-pyweixin` main-window polling path remains a maintenance tool, but the new dialog-based lane better matches upstream `pyweixin`'s own listening examples and avoids forcing the main session list into the foreground all the time.

If you want Holo to react only to one person first, put that name in `whitelist`. The current safe starter is:
- `ContactAlpha`

## JSON Inbox Adapter
The current safe adapter is file-backed.

Each file under `inbox_dir` should be one JSON object:

```json
{
  "chat_name": "测试联系人",
  "sender": "测试联系人",
  "text": "晚上吃什么",
  "channel": "wechat",
  "is_group": false,
  "mentioned": false,
  "message_id": "wx-msg-0001"
}
```

Run:
- `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-inbox`

Processed events are moved into `processed_dir`.
Replies are appended to `outbox_file`.

If `draft_only` is `true`, this stays a safe draft bridge. You can have another tiny Windows script or your own manual workflow read `outbox.jsonl` and decide whether to actually paste/send in WeChat.

## Safety Rails
- `whitelist`: if present, only those chat names are allowed
- `cooldown_seconds`: per-chat send cooldown
- `pause_file`: if the file exists, the helper pauses processing
- `state_file`: remembers seen turns and last-send timestamps

## pywinauto Probe
To inspect the live WeChat UI tree on Windows:

- `py -3 windows_helper\wechat_helper.py probe-wechat`

or point it at a different executable path:

- `py -3 windows_helper\wechat_helper.py probe-wechat --process-path "C:\Program Files\Tencent\Weixin\Weixin.exe"`

This is the intended bridge for the next step: replacing the file-backed inbox with real UI capture and paste/send actions.
