from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from acn_sdk.utils.logging_config import setup_logging
from moq import MOQRelay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start a local MOQ relay for SDK demos.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9003)
    parser.add_argument("--cache-dir", default="data/moq-relay-cache")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    setup_logging()
    logger = logging.getLogger("mock_moq_relay")
    relay = MOQRelay(
        host=args.host,
        port=args.port,
        cache_dir=str(cache_dir),
        max_memory_cache=100 * 1024 * 1024,
        max_disk_cache=1024 * 1024 * 1024,
    )

    logger.info("Starting MOQ relay host=%s port=%s cache_dir=%s", args.host, args.port, cache_dir)
    try:
        await relay.start()
        logger.info("MOQ relay started")
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("MOQ relay stopped by user")
    finally:
        await relay.stop()
        logger.info("MOQ relay shutdown complete")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
