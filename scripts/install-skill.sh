#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "Removing previously installed skill..."
rm -rf ~/.agents/skills/harness 2>/dev/null || true
rm -rf ~/.cursor/skills/harness 2>/dev/null || true

echo "Installing harness skill from local source..."
npx skills add "$REPO_ROOT" -g -a cursor --skill harness -y

echo "Done! The harness skill is installed. Re-run this script after editing skills/harness/."
