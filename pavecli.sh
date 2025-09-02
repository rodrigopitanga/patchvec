#!/usr/bin/env bash
# simple CLI wrapper: prefer project venv; fallback to system python
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$ROOT/.venv-pave/bin/python"

# prefer venv python if available
if [ -x "$VENV_PY" ]; then
  exec "$VENV_PY" -m pave.cli "$@"
fi

# fallback to system python (warn once)
echo "WARN: .venv not found, using system python" >&2
exec python3 -m pave.cli "$@"
