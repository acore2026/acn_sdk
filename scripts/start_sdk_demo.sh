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
python3 mock/mock_acn_agent.py --host 127.0.0.1 --port 9010 > logs/mock_acn_agent.log 2>&1 &
ACN_AGENT_PID=$!
python3 mock/mock_arf.py --host 127.0.0.1 --port 9001 > logs/mock_arf.log 2>&1 &
ARF_PID=$!
python3 mock/mock_agent_gw.py --host 127.0.0.1 --port 9002 > logs/mock_agent_gw.log 2>&1 &
AGENT_GW_PID=$!
python3 mock/mock_moq_relay.py --host 127.0.0.1 --port 9003 --cache-dir data/moq-relay-cache > logs/mock_moq_relay.log 2>&1 &
MOQ_RELAY_PID=$!

cleanup() {
  kill "$ACN_AGENT_PID" >/dev/null 2>&1 || true
  kill "$ARF_PID" >/dev/null 2>&1 || true
  kill "$AGENT_GW_PID" >/dev/null 2>&1 || true
  kill "$MOQ_RELAY_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 3
python3 examples/demo_identity_flow.py
python3 examples/demo_task_flow.py
