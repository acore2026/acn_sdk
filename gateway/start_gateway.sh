#!/usr/bin/env bash
set -euo pipefail

GATEWAY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="${1:-${ACN_GATEWAY_CONFIG:-$GATEWAY_DIR/config.yaml}}"

if [[ ! -f "$CONFIG_PATH" ]]; then
    CONFIG_PATH="$GATEWAY_DIR/config.example.yaml"
fi

export PYTHONPATH="$GATEWAY_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m acn_gateway --config "$CONFIG_PATH"
