#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.holo_runtime/run"
CONFIG_PATH="${HOLO_HOST_CONFIG:-$ROOT_DIR/.holo_host.toml}"

config_port() {
  if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "8004"
    return
  fi
  python3 - <<'PY' "$CONFIG_PATH"
import sys, tomllib
path = sys.argv[1]
with open(path, "rb") as handle:
    data = tomllib.load(handle)
runtime = data.get("runtime", {})
print(int(runtime.get("api_port", 8004)))
PY
}

stop_pidfile() {
  local name="$1"
  local pid_file="$RUN_DIR/${name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name not running"
    return
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "stopped $name (pid $pid)"
  else
    echo "$name stale pid file removed"
  fi
  rm -f "$pid_file"
}

stop_legacy_processes() {
  local api_port
  api_port="$(config_port)"
  local pids
  pids="$(pgrep -f "python3 -m holo_host .*serve-api" || true)"
  if [[ -n "$pids" ]]; then
    while IFS= read -r pid; do
      [[ -n "$pid" ]] || continue
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
      echo "stopped legacy reply_api (pid $pid)"
    done <<<"$pids"
  fi
  pids="$(pgrep -f "python3 -m holo_host .*daemon" || true)"
  if [[ -n "$pids" ]]; then
    while IFS= read -r pid; do
      [[ -n "$pid" ]] || continue
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
      echo "stopped legacy daemon (pid $pid)"
    done <<<"$pids"
  fi
}

stop_pidfile "daemon"
stop_pidfile "reply_api"
stop_legacy_processes
