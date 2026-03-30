from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from acn_sdk.logging_config import setup_logging
from moq.relay import MOQRelay


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
    relay = MOQRelay(host=args.host, port=args.port, cache_dir=str(cache_dir))
    stop_event = asyncio.Event()

    def _request_stop() -> None:
        logger.info("Stop signal received, shutting down MOQ relay.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _request_stop())

    logger.info("Starting MOQ relay host=%s port=%s cache_dir=%s", args.host, args.port, cache_dir)
    await relay.start()
    try:
        await stop_event.wait()
    finally:
        await relay.stop()
        logger.info("MOQ relay stopped.")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
