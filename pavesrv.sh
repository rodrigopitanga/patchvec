#!/usr/bin/env bash
# simple server wrapper: prefer project venv; fallback to system python
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$ROOT/.venv-pave/bin/python"

# defaults are resolved in code via CFG; only pass overrides via env
: "${PATCHVEC_SERVER_HOST:=0.0.0.0}"
: "${PATCHVEC_SERVER_PORT:=8086}"

if [ -x "$VENV_PY" ]; then
  exec "$VENV_PY" -m pave.main
fi

echo "WARN: .venv not found, using system python" >&2
exec python3 -m pave.main
