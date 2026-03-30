#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 not found"
  exit 1
fi

mkdir -p logs
exec "$PYTHON_BIN" mock/mock_moq_relay.py --host 127.0.0.1 --port 9003 --cache-dir data/moq-relay-cache
