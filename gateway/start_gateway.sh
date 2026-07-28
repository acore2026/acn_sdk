#!/usr/bin/env bash
set -euo pipefail

GATEWAY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$GATEWAY_DIR/.." && pwd)"
CONFIG_PATH="${1:-${ACN_GATEWAY_CONFIG:-$GATEWAY_DIR/config.yaml}}"

if [[ ! -f "$CONFIG_PATH" ]]; then
    CONFIG_PATH="$GATEWAY_DIR/config.example.yaml"
fi

PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi

export PYTHONPATH="$GATEWAY_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" -m acn_gateway --config "$CONFIG_PATH"
