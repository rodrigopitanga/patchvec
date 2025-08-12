#!/usr/bin/env bash
set -euo pipefail

# Resolve repo root (dir of this script)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Activate local venv if present
if [[ -d ".venv" && -x ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

# Defaults (override via env)
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8086}"
export WORKERS="${WORKERS:-1}"
export RELOAD="${RELOAD:-1}"   # 1 = dev autoreload (forces WORKERS=1)
export LOG_LEVEL="${LOG_LEVEL:-info}"

# Make project importable without installing
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"

# Auto config path if not provided
if [[ -z "${PATCHVEC_CONFIG:-}" && -f "${ROOT}/config.yml" ]]; then
  export PATCHVEC_CONFIG="${ROOT}/config.yml"
fi

# Pick uvicorn launcher
if command -v uvicorn >/dev/null 2>&1; then
  UVICORN="uvicorn"
else
  UVICORN="python -m uvicorn"
fi

# Compose flags
UV_FLAGS=( "pave.main:app" "--host" "$HOST" "--port" "$PORT" "--log-level" "$LOG_LEVEL" )
if [[ "$RELOAD" == "1" ]]; then
  UV_FLAGS+=( "--reload" )
  WORKERS=1
fi
UV_FLAGS+=( "--workers" "$WORKERS" )

echo "[pavesrv] PYTHONPATH=$PYTHONPATH"
echo "[pavesrv] PATCHVEC_CONFIG=${PATCHVEC_CONFIG:-<unset>}"
echo "[pavesrv] Starting: $UVICORN ${UV_FLAGS[*]}"
exec $UVICORN "${UV_FLAGS[@]}"
