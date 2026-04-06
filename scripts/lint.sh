#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
ruff check src tests
ruff format --check src tests
mypy
