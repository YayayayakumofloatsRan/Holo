#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

'/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe' -ExecutionPolicy Bypass -NoProfile -File "$ROOT_DIR/windows_helper/stop_holo_wechat.ps1" || true
"$ROOT_DIR/scripts/holo-offline.sh"

echo
echo "Holo host + WeChat watcher stopped"
