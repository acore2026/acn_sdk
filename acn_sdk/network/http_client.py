from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from ..models import AgentCardRequest, DeregisterRequest


class SupportsHttpPost(Protocol):
    def post(self, url: str, json: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
        ...

    def close(self) -> None:
        ...


class HttpClient:
    def __init__(self, base_url: str, session: SupportsHttpPost | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._logger = logging.getLogger(self.__class__.__name__)
        # Local SDK-to-agent traffic should not inherit shell proxy settings.
        self._session = session or httpx.Client(base_url=self.base_url, timeout=10.0, trust_env=False)

    def register_robot_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/idm/v1/identity-applications", payload)

    def register_agent_attribute(self, payload: AgentCardRequest) -> dict[str, Any]:
        return self._post("/arf/v1/agent-cards", payload.model_dump(mode="json"))

    def deregister_robot(self, payload: DeregisterRequest) -> dict[str, Any]:
        return self._post("/acn-agent/v1/agent-deletions", payload.model_dump(mode="json"))

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        self._logger.info("HTTP POST %s%s body=%s", self.base_url, path, body)
        response = self._session.post(path, json=body, headers=headers)
        result = response.json()
        self._logger.info("HTTP response %s: %s", path, result)
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP request failed: {response.status_code}, {result}")
        return result

    def close(self) -> None:
        self._logger.info("Closing HttpClient session.")
        self._session.close()
