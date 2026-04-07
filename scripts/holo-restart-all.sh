#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT_DIR/scripts/holo-stop-all.sh"
sleep 1
"$ROOT_DIR/scripts/holo-start-all.sh"
