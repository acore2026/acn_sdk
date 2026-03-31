from __future__ import annotations

import json
import logging
from typing import Any

from ..logging_utils import format_json_for_log


class WebSocketClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self._logger = logging.getLogger(self.__class__.__name__)
        self._connection: Any | None = None

    def connect(self) -> None:
        from websocket import create_connection

        self._logger.info("Connecting websocket to %s", self.url)
        self._connection = create_connection(self.url)
        self._logger.info("Websocket connected.")

    def send_json(self, payload: dict[str, Any]) -> None:
        if self._connection is None:
            raise RuntimeError("WebSocket is not connected.")
        message = json.dumps(payload, ensure_ascii=False)
        self._logger.info("Sending websocket payload\n%s", format_json_for_log(payload))
        self._connection.send(message)

    def receive(self) -> str:
        if self._connection is None:
            raise RuntimeError("WebSocket is not connected.")
        message = self._connection.recv()
        return message

    def receive_json(self) -> dict[str, Any]:
        message = self.receive()
        payload = json.loads(message)
        self._logger.info("Received websocket payload\n%s", format_json_for_log(payload))
        return payload

    def disconnect(self) -> None:
        if self._connection is None:
            return
        self._logger.info("Disconnecting websocket from %s", self.url)
        self._connection.close()
        self._connection = None
