#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"; fi

echo "[1/4] Backend tests"
(
  cd "$PROJECT_DIR/backend"
  "$PYTHON_BIN" -m pytest
)

echo "[2/4] Frontend tests"
(
  cd "$PROJECT_DIR/frontend"
  npm run test
)

echo "[3/4] Frontend lint"
(
  cd "$PROJECT_DIR/frontend"
  npm run lint
)

echo "[4/4] Frontend production build"
(
  cd "$PROJECT_DIR/frontend"
  npm run build
)

echo "All checks passed."
