#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 not found"
  exit 1
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

mkdir -p logs
./scripts/start_mock_services.sh > logs/mock_stack.log 2>&1 &
MOCK_STACK_PID=$!

cleanup() {
  kill "$MOCK_STACK_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 3
python3 examples/demo_identity_flow.py
python3 examples/demo_task_flow.py
