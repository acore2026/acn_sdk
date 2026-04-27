from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import httpx

from ..core.models import (
    AgentCardRequest,
    AgentDiscoveryRequest,
    AgentInfoQueryRequest,
    DeregisterRequest,
    OwnerAgentsQueryRequest,
    TaskExecutionRequest,
    TaskTerminationRequest,
    TaskTerminationBroadcastRequest,
)
from ..utils.logging_utils import format_json_for_log


class SupportsHttpPost(Protocol):
    def post(self, url: str, json: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
        ...

    def close(self) -> None:
        ...


class HttpClient:
    def __init__(
        self,
        base_url: str,
        arf_base_url: str | None = None,
        session: SupportsHttpPost | None = None,
        arf_session: SupportsHttpPost | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.arf_base_url = (arf_base_url or base_url).rstrip("/")
        self._logger = logging.getLogger(self.__class__.__name__)
        # Local SDK-to-agent traffic should not inherit shell proxy settings.
        self._session = session or httpx.Client(base_url=self.base_url, timeout=10.0, trust_env=False)
        self._arf_session = arf_session or httpx.Client(base_url=self.arf_base_url, timeout=10.0, trust_env=False)

    def register_agent_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/idm/v1/identity-applications", payload)

    def register_agent_attribute(self, payload: AgentCardRequest) -> dict[str, Any]:
        return self._post("/arf/v1/agent-cards", payload.model_dump(mode="json"))

    def deregister_agent(self, payload: DeregisterRequest) -> dict[str, Any]:
        return self._post("/acn-agent/v1/agent-deletions", payload.model_dump(mode="json"))

    def request_task_execution(self, payload: TaskExecutionRequest) -> dict[str, Any]:
        return self._post("/acn-agent/v1/task-executions", payload.model_dump(mode="json"))

    def request_terminate_task(self, payload: TaskTerminationRequest) -> dict[str, Any]:
        return self._post("/acn-agent/v1/task-execution-terminations", payload.model_dump(mode="json"))

    def broadcast_terminate_task(self, payload: TaskTerminationBroadcastRequest) -> tuple[bool, str]:
        headers = {"Content-Type": "application/json"}
        body = payload.model_dump(mode="json")
        self._logger.info(
            "HTTP POST %s%s\n%s",
            self.base_url,
            "/acn-agent/v1/task-termination-broadcasts",
            format_json_for_log(body),
        )
        response = self._session.post("/acn-agent/v1/task-termination-broadcasts", json=body, headers=headers)
        if response.status_code == 200:
            self._logger.info("HTTP response /acn-agent/v1/task-termination-broadcasts with status=200")
            return (True, "")

        error_message = self._extract_error_message(response)
        self._logger.info(
            "HTTP response /acn-agent/v1/task-termination-broadcasts failed with status=%s\n%s",
            response.status_code,
            error_message,
        )
        return (False, f"HTTP request failed: {response.status_code}, {error_message}")

    def request_task_collaboration(self, payload: AgentDiscoveryRequest) -> dict[str, Any]:
        return self._post("/arf/v1/agent-discoveries", payload.model_dump(mode="json"), use_arf=True)

    def query_agent_info(self, payload: AgentInfoQueryRequest) -> dict[str, Any]:
        return self._post("/arf/v1/agent-info", payload.model_dump(mode="json"), use_arf=True)

    def query_agent_list(self, payload: OwnerAgentsQueryRequest) -> dict[str, Any]:
        return self._post("/acn-agent/v1/owner-agents", payload.model_dump(mode="json"))

    def _post(self, path: str, body: dict[str, Any], use_arf: bool = False) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        target_base_url = self.arf_base_url if use_arf else self.base_url
        target_session = self._arf_session if use_arf else self._session
        self._logger.info(
            "HTTP POST %s%s\n%s",
            target_base_url,
            path,
            format_json_for_log(body),
        )
        response = target_session.post(path, json=body, headers=headers)
        result = response.json()
        self._logger.info(
            "HTTP response %s\n%s",
            path,
            format_json_for_log(result),
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP request failed: {response.status_code}, {result}")
        return result

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            text = response.text.strip()
            return text or "unknown error"
        return json.dumps(payload, ensure_ascii=False) if payload != "" else "unknown error"

    def close(self) -> None:
        self._logger.info("Closing HttpClient session.")
        self._session.close()
        if self._arf_session is not self._session:
            self._arf_session.close()
