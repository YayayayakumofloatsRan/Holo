#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${HOLO_HOST_CONFIG:-$ROOT_DIR/.holo_host.toml}"

"$ROOT_DIR/scripts/holo-online.sh"

python3 - <<'PY' "$CONFIG_PATH"
import sys, time, tomllib
from urllib import request

path = sys.argv[1]
with open(path, "rb") as handle:
    data = tomllib.load(handle)
runtime = data.get("runtime", {})
host = runtime.get("api_bind_host", "127.0.0.1")
port = int(runtime.get("api_port", 8004))
url = f"http://{host}:{port}/health"
opener = request.build_opener(request.ProxyHandler({}))
last_exc = None
for _ in range(20):
    try:
        opener.open(url, timeout=2).read()
        raise SystemExit(0)
    except Exception as exc:  # noqa: BLE001
        last_exc = exc
        time.sleep(0.5)
raise SystemExit(f"reply api did not become healthy in time: {last_exc}")
PY
'/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe' -ExecutionPolicy Bypass -NoProfile -File "$ROOT_DIR/windows_helper/start_holo_wechat.ps1"

echo
echo "Holo host + WeChat watcher started"
