#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
[[ "${1:-}" == -i || "${1:-}" == --integration ]] && { export CURSOR_DRIVER_INTEGRATION=1; shift; }
exec python -m pytest -v "${@:-tests/}"
