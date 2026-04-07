#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.holo_runtime"
RUN_DIR="$RUNTIME_DIR/run"
LOG_DIR="$RUNTIME_DIR/logs"
CONFIG_PATH="${HOLO_HOST_CONFIG:-$ROOT_DIR/.holo_host.toml}"
PYTHON_BIN="${HOLO_HOST_PYTHON:-python3}"

mkdir -p "$RUN_DIR" "$LOG_DIR"

ensure_default_config() {
  if [[ -f "$CONFIG_PATH" ]]; then
    return
  fi
  cat >"$CONFIG_PATH" <<'EOF'
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "codex_cli"
poll_interval_seconds = 30
max_jobs_per_cycle = 4
codex_binary = "codex"
codex_model = "gpt-5.4"
codex_reasoning_effort = "low"
fast_model = "gpt-5.4-mini"
fast_reasoning_effort = "low"
responses_model = "gpt-5.4"
responses_fast_model = "gpt-5.4-mini"
network_enabled = true
image_enabled = true
codex_timeout_seconds = 900
resume_sessions = true
dry_run = false
api_bind_host = "0.0.0.0"
api_port = 8004

[mail]
transport = "maildir"
poll_limit = 10
maildir_inbox = ".holo_runtime/mail/inbox"
maildir_processed = ".holo_runtime/mail/processed"
maildir_outbox = ".holo_runtime/mail/outbox"

[memory]
prompt_top_k = 4
auto_observe = true
promote_batch_size = 8
promote_interval_seconds = 300
dream_interval_seconds = 1800
dream_sample_size = 6
history_messages = 8

[autonomy]
auto_send_mode = "full_auto"
allow_proactive_existing_threads = true
proactive_after_hours = 72
max_auto_replies_per_contact_per_hour = 12
EOF
}

is_running() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  if kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  rm -f "$pid_file"
  return 1
}

start_detached() {
  local name="$1"
  shift
  local pid_file="$RUN_DIR/${name}.pid"
  local log_file="$LOG_DIR/${name}.log"
  if is_running "$pid_file"; then
    echo "$name already running (pid $(cat "$pid_file"))"
    return
  fi
  local launcher_pid
  launcher_pid="$(
    python3 - <<'PY' "$pid_file" "$log_file" "$ROOT_DIR" "$@"
import os
import subprocess
import sys
from pathlib import Path

pid_path = Path(sys.argv[1])
log_path = Path(sys.argv[2])
cwd = sys.argv[3]
cmd = sys.argv[4:]

log_path.parent.mkdir(parents=True, exist_ok=True)
with open(os.devnull, "rb") as devnull, open(log_path, "ab", buffering=0) as log_handle:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=devnull,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )

pid_path.write_text(str(proc.pid), encoding="utf-8")
print(proc.pid)
PY
  )"
  sleep 1
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "$name failed to start; see $log_file" >&2
    exit 1
  fi
  echo "started $name (pid $launcher_pid)"
}

ensure_default_config
cd "$ROOT_DIR"

"$PYTHON_BIN" - <<'PY' "$CONFIG_PATH"
from pathlib import Path
import re
import sys

config_path = Path(sys.argv[1])
text = config_path.read_text(encoding="utf-8")
updated = text
if re.search(r'(?m)^\s*api_bind_host\s*=\s*"([^"]+)"', text):
    updated = re.sub(r'(?m)^(\s*api_bind_host\s*=\s*")([^"]+)(".*)$', r'\g<1>0.0.0.0\3', text, count=1)
else:
    updated = text.replace('api_port = 8004', 'api_bind_host = "0.0.0.0"\napi_port = 8004', 1)
if updated != text:
    config_path.write_text(updated, encoding="utf-8")
PY

start_detached "reply_api" "$PYTHON_BIN" -m holo_host --config "$CONFIG_PATH" serve-api --host 0.0.0.0
start_detached "daemon" "$PYTHON_BIN" -m holo_host --config "$CONFIG_PATH" daemon

echo
echo "Holo runtime is online"
echo "config: $CONFIG_PATH"
echo "logs:   $LOG_DIR"
