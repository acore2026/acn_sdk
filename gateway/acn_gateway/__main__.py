from __future__ import annotations

import argparse

import uvicorn

from .app import create_app, default_config_path
from .config import GatewaySettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ACN Android trigger Gateway")
    parser.add_argument("--config", default=str(default_config_path()), help="Gateway YAML configuration")
    args = parser.parse_args()
    settings = GatewaySettings.load(args.config)
    uvicorn.run(
        create_app(args.config),
        host=settings.server.host,
        port=settings.server.port,
        log_level=settings.python_sdk.log_level.lower(),
    )


if __name__ == "__main__":
    main()
