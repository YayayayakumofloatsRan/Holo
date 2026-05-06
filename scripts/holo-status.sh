#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.holo_runtime/run"
CONFIG_PATH="${HOLO_HOST_CONFIG:-$ROOT_DIR/.holo_host.toml}"

show_pid() {
  local name="$1"
  local pid_file="$RUN_DIR/${name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name: stopped"
    return
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "$name: running (pid $pid)"
  else
    echo "$name: stale pid file"
  fi
}

show_pid "reply_api"
show_pid "daemon"

python3 - <<'PY' "$ROOT_DIR/windows_helper/wechat_helper.live.json"
import json
import re
import sys
import time
from pathlib import Path

config_path = Path(sys.argv[1])
if not config_path.exists():
    print("transport: unavailable (missing live config)")
    raise SystemExit(0)

def windows_to_wsl(raw: str) -> Path:
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        drive = raw[0].lower()
        tail = raw[2:].lstrip("\\/").replace("\\", "/")
        return Path("/mnt") / drive / tail
    return Path(raw)

try:
    config = json.loads(config_path.read_text(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001
    print(f"transport: unavailable (invalid live config: {exc})")
    raise SystemExit(0)

state_path = windows_to_wsl(str(config.get("transport_state_file", "")))
if not state_path or not state_path.exists():
    print("transport: stopped (no transport state file)")
    raise SystemExit(0)

try:
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
except Exception as exc:  # noqa: BLE001
    print(f"transport: unknown (invalid transport state: {exc})")
    raise SystemExit(0)

heartbeat = int(state.get("heartbeat_at", 0) or 0)
age = max(0, int(time.time()) - heartbeat) if heartbeat else -1
status = str(state.get("status", "unknown") or "unknown")
mode = str(state.get("mode", "") or "")
transport = str(state.get("transport", "") or "")
detail = str(state.get("detail", "") or "")
if heartbeat and age > 45 and status not in {"stopped"}:
    status = "stale"
print(f"transport: {status} mode={mode or 'unknown'} transport={transport or 'unknown'} heartbeat_age_s={age}")
if detail:
    print(f"transport_detail: {detail}")
PY

echo "legacy_processes:"
ps -eo pid,ppid,pgid,cmd | grep -E 'python3 -m holo_host .*serve-api|python3 -m holo_host .*daemon' | grep -v grep || true

if [[ -f "$CONFIG_PATH" ]]; then
  python3 - <<'PY' "$CONFIG_PATH"
import sys, tomllib
from urllib import request

path = sys.argv[1]
with open(path, "rb") as handle:
    data = tomllib.load(handle)
runtime = data.get("runtime", {})
host = runtime.get("api_bind_host", "127.0.0.1")
port = runtime.get("api_port", 8004)
url = f"http://{host}:{port}/health"
try:
    opener = request.build_opener(request.ProxyHandler({}))
    body = opener.open(url, timeout=3).read().decode("utf-8")
    print(f"health: ok {url}")
    print(body)
except Exception as exc:  # noqa: BLE001
    print(f"health: unavailable {url} ({exc})")
PY
fi
