from __future__ import annotations

import json
import logging
from threading import Lock
from typing import Any

import httpx


class PipelineLogReporter:
    def __init__(self, web_ui_url: str, session: httpx.Client | None = None) -> None:
        self.web_ui_url = web_ui_url.rstrip("/")
        self._logger = logging.getLogger(self.__class__.__name__)
        self._session = session or httpx.Client(base_url=self.web_ui_url, timeout=3.0, trust_env=False)
        self._lock = Lock()

    def report(
        self,
        *,
        source: str,
        destination: str,
        protocol: str,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        abstract: str = "",
        content: Any = "",
        task_id: str | None = None,
    ) -> None:
        payload = {
            "method": "POST",
            "url": "/acn/v3/pipeline-logs",
            "headers": {
                "Content-Type": "application/json",
            },
            "body": {
                "source": source,
                "destination": destination,
                "timestamp": self._utc_timestamp(),
                "task_id": task_id,
                "protocol": protocol,
                "headers": self._stringify_headers(headers),
                "abstract": abstract,
                "content": self._stringify_value(content),
            },
        }

        try:
            with self._lock:
                self._session.post("/acn/v3/pipeline-logs", json=payload, headers={"Content-Type": "application/json"})
        except Exception as exc:
            pass
            # self._logger.warning(
            #     "Failed to report pipeline log source=%s destination=%s protocol=%s method=%s url=%s error=%s",
            #     source,
            #     destination,
            #     protocol,
            #     method,
            #     url,
            #     exc,
            # )

    def close(self) -> None:
        self._session.close()

    @staticmethod
    def _utc_timestamp() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _stringify_value(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)

    @staticmethod
    def _stringify_headers(headers: dict[str, str] | None) -> str:
        if not headers:
            return ""
        return PipelineLogReporter._stringify_value(headers)
