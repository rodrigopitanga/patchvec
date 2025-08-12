#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Activate local venv if present
if [[ -d ".venv" && -x ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

# Make project importable without installing
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"

# Auto config path if not provided
if [[ -z "${PATCHVEC_CONFIG:-}" && -f "${ROOT}/config.yml" ]]; then
  export PATCHVEC_CONFIG="${ROOT}/config.yml"
fi

# Run CLI
exec python -m pave.cli "$@"
