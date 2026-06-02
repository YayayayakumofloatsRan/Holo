#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${HOME}/.local/bin"
TARGET="${TARGET_DIR}/holo-v3"

mkdir -p "${TARGET_DIR}"

cat >"${TARGET}" <<EOF
#!/usr/bin/env bash
exec "${ROOT}/holo-v3" "\$@"
EOF

chmod +x "${TARGET}"
chmod +x "${ROOT}/holo-v3"

case ":${PATH}:" in
  *:"${TARGET_DIR}":*) ;;
  *)
    echo "Installed ${TARGET}, but ${TARGET_DIR} is not currently on PATH." >&2
    echo "Add this to your shell profile: export PATH=\"${TARGET_DIR}:\$PATH\"" >&2
    exit 2
    ;;
esac

echo "Installed ${TARGET}"
