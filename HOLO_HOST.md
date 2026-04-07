# Holo Host

Cross-thread handoff docs:
- `HOLO_HANDOFF.md`
- `HOLO_SYSTEM.md`
- `HOLO_DEVELOPMENT.md`

This is the first WSL-native outer body for Holo.

For now, the production compute brain is `codex_cli`. The Responses API path stays available as a future backend, but it is not the default runtime here.

It keeps the processor as a replaceable "compute brain", while a local daemon handles:
- inbox polling
- queueing and SQLite state
- processor invocation
- reply repair through `holo_memory_library`
- automatic memory observation and delayed promotion
- archive backfill, replay, and callback-candidate staging

## Main Pieces
- `holo_host/store.py`: SQLite contacts / threads / messages / jobs
- `holo_host/mail_gateway.py`: `maildir` transport for local testing, `imap_smtp` transport for real mail
- `holo_host/codex_runner.py`: wraps `codex exec` and `codex exec resume`
- `holo_host/processors.py`: fast/main routing, structured `ReplyPlan`, `TurnPlan`, multi-bubble planning, processor abstraction
- `holo_host/capabilities.py`: bounded web/artifact/image context broker
- `holo_host/memory_bridge.py`: bridges into `holo_memory_library`
- `holo_host/daemon.py`: ingest -> queue -> reply -> observe -> promote loop
- `holo_host/reply_api.py`: local Codex-direct HTTP bridge for Windows helpers
- `holo_host/cli.py`: local runtime commands
- `windows_helper/`: thin Windows-side shell for talking to the local reply API

## Local Commands
- `python3 -m holo_host init-db`
- `python3 -m holo_host cycle`
- `python3 -m holo_host jobs --limit 20`
- `python3 -m holo_host schedule-followups`
- `python3 -m holo_host promote-memory`
- `python3 -m holo_host backfill-archive [--db-path .holo_runtime/holo_host.sqlite3]`
- `python3 -m holo_host dream-cycle [--sample-size 6]`
- `python3 -m holo_host show-callbacks --limit 20`
- `python3 -m holo_host inspect-mind --thread-key ContactAlpha --chat-name ContactAlpha --query "你还记得重新上线前吗"`
- `python3 -m holo_host backfill-mind-graph [--dry-run]`
- `python3 -m holo_host inspect-graph --thread-key ContactAlpha --chat-name ContactAlpha`
- `python3 -m holo_host trace-recall --thread-key ContactAlpha --chat-name ContactAlpha --query "你还记得重新上线前吗"`
- `python3 -m holo_host show-stream-status`
- `python3 -m holo_host show-processor-mesh`
- `python3 -m holo_host processor-task --task-type self_check --prompt "..."`
- `python3 -m holo_host snapshot-memory --label before-migration`
- `python3 -m holo_host restore-memory --path .holo_runtime/snapshots/...json --dry-run`
- `python3 -m holo_host revive-packet [--path .holo_runtime/snapshots/...json]`
- `python3 -m holo_host ingest-artifact --path ./notes.md --dry-run`
- `python3 -m holo_host serve-api`
- `python3 -m holo_host daemon`
- `./scripts/holo-online.sh`
- `./scripts/holo-offline.sh`
- `./scripts/holo-status.sh`

## Config
Copy `.holo_host.example.toml` to `.holo_host.toml` and adjust it.

Default local-safe mode uses the filesystem maildir transport:
- incoming test mail goes into `.holo_runtime/mail/inbox`
- processed mail moves to `.holo_runtime/mail/processed`
- outgoing replies are written to `.holo_runtime/mail/outbox`

For real mail, switch `transport = "imap_smtp"` and provide the account settings plus the mail password through the env var named by `password_env`.

The local reply API also has bind settings under `[runtime]`:
- `api_bind_host = "127.0.0.1"`
- `api_port = 8000`

## Delivery Model
- New inbound mail becomes a normalized `IncomingMessage`
- The daemon records it in SQLite and enqueues a `reply` job
- The reply job builds a structured mind packet before prompt assembly
- The mind packet uses adaptive `fast` / `recall` tiers instead of assuming one thin prompt pack
- The processor returns a draft plus a structured `ReplyPlan`
- `reply-loop` repairs drift, then a bubble planner shapes the result into 1-4 chat bubbles
- The final reply is sent through the configured gateway
- The turn is auto-observed into candidate memory and also archived as a full user/reply pair inside Holo memory
- Ready candidates are promoted on a slower background cadence
- A slower dream cadence samples the archive with weighted randomness, distills repeated patterns, and stages callback leads for old threads
- The host can also write a portable self snapshot and emit a compact revive packet for another main program

## Codex-Direct Reply API
This path is meant for helpers such as a Windows WeChat automation shell.

The helper calls into WSL; WSL then:
- records the incoming turn into SQLite
- resumes or starts the right `codex exec` session for that thread
- treats `codex_session_id` only as resumable compute cache, not as identity continuity
- builds a structured memory-aware prompt pack from local memory and runtime state
- computes a structured turn plan with attention, route, bubble target, and bounded tool mode
- repairs the draft through `reply-loop`
- records the outbound turn and auto-observes memory
- archives the full turn into Holo's conversation ledger for later replay or cross-host revival
- can backfill older runtime messages into that same archive and replay them into candidate memory later
- can also ingest local artifacts such as notes, captured history exports, PDFs, DOCX files, and image-sidecar bundles into Holo memory

Run it with:
- `python3 -m holo_host serve-api`
- or bring the detached runtime online with `./scripts/holo-online.sh`

Available endpoints:
- `GET /health`
- `GET /mind-graph`
- `GET /trace-recall`
- `GET /stream-status`
- `POST /reply`
- `POST /snapshot`
- `POST /restore-snapshot`
- `POST /ingest-artifact`
- `GET /revive-packet`

`inspect-mind` is the quickest observability entry when Holo feels blank. It prints the chosen tier, injected memory ids, thread recall lines, consciousness lines, and the relationship summary for a specific query/thread pair.

`inspect-graph` and `trace-recall` are the new Mind OS observability pair:
- `inspect-graph` shows what the SQLite Mind Graph materialized for a thread
- `trace-recall` shows which nodes would activate for a recall-style query

The processor mesh foundation now lives in `holo_host/codex_runner.py`. `reply` is still the live task, but the runtime now has explicit task types for recall reconstruction, consolidation, dream/reflect, initiative planning, and self-check.

Minimal `POST /reply` body:
```json
{
  "chat_name": "测试联系人",
  "sender": "测试联系人",
  "text": "我最近有点累",
  "is_group": false,
  "mentioned": false,
  "channel": "wechat"
}
```

Typical response:
```json
{
  "action": "reply",
  "text": "咱看得出你是真累了 今晚先别再和自己较劲",
  "bubbles": [
    "咱看得出你是真累了",
    "今晚先别再和自己较劲"
  ],
  "cadence_ms": [0, 680],
  "turn_plan": {
    "route": "fast",
    "fast_path": true,
    "bubble_target": 2,
    "tool_mode": "none"
  },
  "thread_key": "wechat:测试联系人",
  "session_id": "thread-123",
  "processor": "codex_cli",
  "route": "fast",
  "timing_ms": {
    "sidecar_ms": 8,
    "capability_ms": 1,
    "processor_ms": 120,
    "repair_ms": 18,
    "total_ms": 161
  }
}
```

Minimal `POST /ingest-artifact` body:
```json
{
  "path": "/home/ran_yakumo/holo/notes/travel.docx",
  "note": "这是用户给咱看的作品笔记。",
  "tags": ["wechat_export", "artifact"],
  "dry_run": true
}
```

## Windows WeChat Transports
The Windows helper now has two transport lanes:
- `json_inbox`: the safe file-backed bridge for manual or sidecar integrations
- `wcf`: a `wcferry` / WeChatFerry-backed lane for live personal-account message receive/send on Windows

Useful Windows-side commands:
- `wechat_helper.py health`
- `wechat_helper.py send-turn --chat-name 测试联系人 --text 我最近有点累`
- `wechat_helper.py ingest-artifact --path C:\wechat-helper\exports\notes.md --dry-run`
- `wechat_helper.py wcf-info`
- `wechat_helper.py wcf-contacts --needle ContactAlpha`
- `wechat_helper.py watch-live`
- `wechat_helper.py watch-wcf`
- `wechat_helper.py watch-pyweixin-dialog`
- `wechat_helper.py watch-pyweixin`
- `wechat_helper.py watch-pyweixin --once`
- `pythonw.exe windows_helper\\pyweixin_watcher.pyw --config C:\wechat-helper\wechat_helper.json`
- `wechat_helper.py probe-pyweixin`
- `wechat_helper.py prime-pyweixin --restart-weixin --wait-seconds 8`
- `wechat_helper.py send-pyweixin --chat-name ContactAlpha --text "咱来找你了。"`
- `wechat_helper.py read-pyweixin-visible --chat-name 文件传输助手 --limit 10 --capture-dir C:\wechat-helper\history_captures`
- `wechat_helper.py read-pyweixin-history --chat-name 文件传输助手 --limit 20 --page-turns 10 --capture-dir C:\wechat-helper\history_captures`
- `wechat_helper.py ingest-pyweixin-history --chat-name 文件传输助手 --limit 20 --page-turns 10 --dry-run`
- `wechat_helper.py ingest-pyweixin-history --chat-name 文件传输助手 --limit 20 --page-turns 10 --force`

The intended deployment shape stays the same:
- Windows does message ingress/egress
- WSL does Codex, memory, and reply repair

The old `wcf` path is no longer the intended online path on this machine. `wcf-info` now makes the mismatch explicit: the installed `wcferry 39.x` line is publicly documented around the `3.9.x` client line, while the local desktop client is `Weixin 4.1.x`.
For `Weixin 4.1+`, the helper now grows a dialog-based `pyweixin_dialog` transport: one dedicated minimized dialog window per whitelisted chat, listened to through upstream `pyweixin`'s own monitor methods. That is the new intended online direction.
`watch-pyweixin` still exists, but it is now the maintenance lane for main-window probing, history capture, and rich-media extraction. When it sees a rich-media message that yields a capture, it forwards that capture to the WSL memory bridge so Holo can keep the artifact, not just the one-line placeholder text.

## Resurrection Path
- `snapshot-memory` writes an explicit self bundle under `.holo_runtime/snapshots/` by default, including structured memory plus the full conversation archive
- `restore-memory` merges or replaces memory from a saved bundle; use `--restore-persona-files` if the target runtime should also restore `.holo.md` and persona markdown
- `revive-packet` prints a compact explicit packet for black-box hosts that cannot import the full stores directly

## Proactive Followup
The first version can schedule proactive followups only for existing threads.

Rules:
- no new-contact cold outreach
- no forwarding or CC fanout
- followups are only queued after a thread has gone quiet for `proactive_after_hours`

## Deployment Notes
Recommended on WSL:
- long-running service: `systemd --user` service or a `tmux` fallback
- state: `.holo_runtime/`
- config: `.holo_host.toml`

Sample unit files live under `deploy/systemd/`.

For this repo, the current practical launcher is the shell supervisor:
- `./scripts/holo-online.sh`: starts detached `reply_api` and `daemon`, writes pid files under `.holo_runtime/run`
- `./scripts/holo-offline.sh`: stops detached runtime processes and removes pid files
- `./scripts/holo-status.sh`: shows kernel pid-file status, transport heartbeat/state, legacy leftovers, and local `/health`

These scripts matter because Holo's memory and archive live outside any one Codex chat thread. The thread may die; the detached runtime should keep the processor callable.

## CLI Archive Note
Repo-local Codex CLI conversations are meant to be preserved in the same archive ledger as transport turns.

Key files:
- `/.codex/hooks.json`
- `holo_memory_library/codex_hooks/user_prompt_submit.py`
- `holo_memory_library/codex_hooks/stop_revise.py`

Quick check:
- `python3 holo_memory_library/rag_memory.py show-archive --channel codex_cli --limit 5`

Do not disable or repoint these hooks casually, or Codex-thread history will stop entering Holo's archive.
