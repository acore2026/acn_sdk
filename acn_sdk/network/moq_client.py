from __future__ import annotations

import logging
from collections import defaultdict


class MoQClient:
    def __init__(self, host: str, remote_port: int, local_port: int, role: str) -> None:
        self.host = host
        self.remote_port = remote_port
        self.local_port = local_port
        self.role = role
        self._logger = logging.getLogger(self.__class__.__name__)
        self._subscriptions: dict[str, list[str]] = defaultdict(list)

    def connect(self) -> None:
        self._logger.info(
            "MoQ client connected role=%s local_port=%s remote=%s:%s",
            self.role,
            self.local_port,
            self.host,
            self.remote_port,
        )

    def publish(self, track: str, payload: str) -> None:
        self._logger.info("MoQ publish track=%s payload=%s", track, payload)

    def subscribe(self, track: str, subscriber_id: str) -> None:
        self._subscriptions[track].append(subscriber_id)
        self._logger.info("MoQ subscribe track=%s subscriber=%s", track, subscriber_id)

    def disconnect(self) -> None:
        self._logger.info(
            "MoQ client disconnected role=%s local_port=%s remote=%s:%s",
            self.role,
            self.local_port,
            self.host,
            self.remote_port,
        )
        self._subscriptions.clear()
