from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from .config import GatewaySettings


SdkFactory = Callable[[Path], Any]


@dataclass(slots=True)
class ServiceResult:
    result: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class GatewayService:
    """Owns one Python AcnSDK instance and exposes idempotent trigger operations."""

    def __init__(self, settings: GatewaySettings, sdk_factory: SdkFactory | None = None) -> None:
        self.settings = settings
        self._sdk_factory = sdk_factory
        self._sdk: Any | None = None
        self._agent_info_type: type[Any] | None = None
        self._lock = threading.RLock()
        self._logger = logging.getLogger(self.__class__.__name__)
        self.agent_id: str | None = None
        self.current_task_id: str | None = None
        self.identity_registered = False
        self.capabilities_registered = False
        self.network_status = "offline"
        self.task_status = "idle"
        self.last_error = ""
        self.moq_messages_received = 0

    @property
    def sdk(self) -> Any:
        if self._sdk is None:
            raise RuntimeError("Gateway service has not been started")
        return self._sdk

    def start(self) -> None:
        with self._lock:
            if self._sdk is not None:
                return
            sdk_config_path = self.settings.write_python_sdk_config()
            if self._sdk_factory is not None:
                self._sdk = self._sdk_factory(sdk_config_path)
                self._agent_info_type = None
            else:
                source_path = self.settings.python_sdk.source_path
                if source_path not in sys.path:
                    sys.path.insert(0, source_path)
                from acn_sdk.core.models import AgentInfo
                from acn_sdk.sdk import AcnSDK

                self._agent_info_type = AgentInfo
                self._sdk = AcnSDK(self.settings.agent.name, config_path=sdk_config_path)

            ok, message = self.sdk.register_callbacks(
                on_task_collaboration_request=self._on_task_collaboration_request,
                on_discover_result_received=self._on_discover_result,
                on_task_start_command=self._on_task_start,
                on_terminate_task_received=self._on_task_termination,
                on_subscribe_track_received=self._on_subscribe_track,
                on_message_received=self._on_moq_message,
            )
            if not ok:
                self._sdk = None
                raise RuntimeError(f"Failed to register Python SDK callbacks: {message}")

    def stop(self) -> None:
        with self._lock:
            if self._sdk is None:
                return
            try:
                self.sdk.disconnect_all(clear_task_registry=False)
            finally:
                self._sdk = None
                self.network_status = "offline"

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "agent_id": self.agent_id,
                "current_task_id": self.current_task_id,
                "identity_registered": self.identity_registered,
                "capabilities_registered": self.capabilities_registered,
                "network_status": self.network_status,
                "task_status": self.task_status,
                "last_error": self.last_error,
                "moq_messages_received": self.moq_messages_received,
            }

    def register_identity(self) -> ServiceResult:
        with self._lock:
            if self.agent_id:
                return self._success("Identity is already registered", agent_id=self.agent_id)
            agent = self.settings.agent
            values = agent.model_dump(mode="python")
            agent_info = self._agent_info_type(**values) if self._agent_info_type else SimpleNamespace(**values)
            ok, message = self.sdk.register_agent_info(agent_info)
            if not ok:
                return self._failure(message)
            self.agent_id = message
            self.identity_registered = True
            return self._success(agent_id=message)

    def register_capabilities(self) -> ServiceResult:
        with self._lock:
            agent_id = self._require_agent_id()
            if isinstance(agent_id, ServiceResult):
                return agent_id
            ok, message = self.sdk.register_agent_attribute(agent_id, self.settings.capabilities)
            if not ok:
                return self._failure(message)
            self.capabilities_registered = True
            return self._success(data=self.settings.capabilities, sdk_response=message)

    def join_network(self) -> ServiceResult:
        with self._lock:
            agent_id = self._require_agent_id()
            if isinstance(agent_id, ServiceResult):
                return agent_id
            if self.network_status == "online":
                return self._success("Agent is already online")
            ok, message = self.sdk.join_network(agent_id)
            if not ok:
                return self._failure(message)
            self.network_status = "online"
            return self._success()

    def execute_task(self) -> ServiceResult:
        with self._lock:
            agent_id = self._require_online_agent_id()
            if isinstance(agent_id, ServiceResult):
                return agent_id
            if self.task_status in {"processing", "terminating"}:
                return self._failure(f"Task {self.current_task_id} is still {self.task_status}")
            ok, message = self.sdk.request_task_execution(
                agent_id,
                self.settings.task.description,
                task_id=None,
            )
            if not ok:
                return self._failure(message)
            self.current_task_id = message
            self.task_status = "processing"
            return self._success(task_id=message)

    def broadcast_terminate_task(self) -> ServiceResult:
        with self._lock:
            agent_id = self._require_online_agent_id()
            if isinstance(agent_id, ServiceResult):
                return agent_id
            if not self.current_task_id or self.task_status != "processing":
                return self._failure("No processing task is available to terminate")
            task_id = self.current_task_id
            ok, message = self.sdk.broadcast_terminate_task(
                agent_id,
                task_id,
                self.settings.task.termination_reason,
                self.settings.task.termination_force,
            )
            if not ok:
                return self._failure(message)
            self.task_status = "terminating"
            return self._success(task_id=task_id)

    def logout_network(self) -> ServiceResult:
        with self._lock:
            agent_id = self._require_agent_id()
            if isinstance(agent_id, ServiceResult):
                return agent_id
            if self.network_status == "offline":
                return self._success("Agent is already offline")
            if self.task_status in {"processing", "terminating"}:
                return self._failure("Wait for task termination before logging out")
            ok, message = self.sdk.logout_network(agent_id)
            if not ok:
                return self._failure(message)
            self.network_status = "offline"
            return self._success()

    def deregister(self) -> ServiceResult:
        with self._lock:
            agent_id = self._require_agent_id()
            if isinstance(agent_id, ServiceResult):
                return agent_id
            if self.task_status in {"processing", "terminating"}:
                return self._failure("Wait for task termination before deregistration")
            ok, message = self.sdk.deregister_agent(agent_id, self.settings.deregister.reason)
            if not ok:
                return self._failure(message)
            removed_agent_id = agent_id
            self.agent_id = None
            self.current_task_id = None
            self.identity_registered = False
            self.capabilities_registered = False
            self.network_status = "offline"
            self.task_status = "idle"
            return self._success(agent_id=removed_agent_id, sdk_response=message)

    def _on_task_collaboration_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            task_id = payload.get("task_id")
            if isinstance(task_id, str) and task_id:
                self.current_task_id = task_id
            if not self.agent_id or not self.current_task_id:
                self._record_callback_error("Collaboration request is missing agent_id or task_id")
                return
            ok, message = self.sdk.accept_task_collaboration(self.agent_id, self.current_task_id)
            if not ok:
                self._record_callback_error(message)

    def _on_discover_result(self, payload: dict[str, Any]) -> None:
        with self._lock:
            candidates = payload.get("discover_result")
            if not isinstance(candidates, list) or not candidates:
                self._record_callback_error("discover_result is empty")
                return
            candidate = candidates[0]
            if isinstance(candidate, dict):
                candidate = candidate.get("agent_id")
            if not isinstance(candidate, str) or not candidate:
                self._record_callback_error("First discover result does not contain an agent_id")
                return
            task_id = payload.get("task_id") or self.current_task_id
            if not self.agent_id or not isinstance(task_id, str) or not task_id:
                self._record_callback_error("Discover result is missing local agent_id or task_id")
                return
            self.current_task_id = task_id
            ok, message = self.sdk.start_task_collaboration(
                self.agent_id,
                candidate,
                task_id,
                self.settings.task.collaboration_description,
            )
            if not ok:
                self._record_callback_error(message)

    def _on_task_start(self, payload: dict[str, Any]) -> None:
        with self._lock:
            task_id = payload.get("task_id")
            description = payload.get("task_description") or self.settings.task.description
            if not self.agent_id or not isinstance(task_id, str) or not task_id:
                self._record_callback_error("START_TASK is missing local agent_id or task_id")
                return
            ok, message = self.sdk.request_task_execution(self.agent_id, str(description), task_id=task_id)
            if not ok:
                self._record_callback_error(message)
                return
            self.current_task_id = task_id
            self.task_status = "processing"

    def _on_task_termination(self, payload: dict[str, Any]) -> None:
        with self._lock:
            task_id = payload.get("task_id")
            reason = payload.get("reason") or self.settings.task.termination_reason
            if not self.agent_id or not isinstance(task_id, str) or not task_id:
                self._record_callback_error("TASK_TERMINATION is missing local agent_id or task_id")
                return
            ok, message = self.sdk.request_terminate_task(
                self.agent_id,
                task_id,
                str(reason),
                self.settings.task.termination_force,
            )
            if not ok:
                self._record_callback_error(message)
                return
            self.current_task_id = task_id
            self.task_status = "terminated"

    def _on_subscribe_track(self, payload: dict[str, Any]) -> dict[str, str]:
        fetch_tracks = set(self.settings.callbacks.fetch_tracks)
        modes: dict[str, str] = {}
        for track_info in payload.get("track_list", []):
            namespace = track_info.get("namespace")
            track = track_info.get("track")
            if isinstance(namespace, str) and isinstance(track, str):
                modes[f"{namespace}::{track}"] = "fetch" if track in fetch_tracks else "subscribe"
        return modes

    def _on_moq_message(self, namespace: str, track: str, payload: bytes) -> None:
        with self._lock:
            self.moq_messages_received += 1
            if self.settings.callbacks.moq_message_policy == "log":
                self._logger.info(
                    "MoQ message consumed in Gateway namespace=%s track=%s payload_size=%d",
                    namespace,
                    track,
                    len(payload),
                )

    def _require_agent_id(self) -> str | ServiceResult:
        if not self.agent_id:
            return self._failure("Register identity first")
        return self.agent_id

    def _require_online_agent_id(self) -> str | ServiceResult:
        agent_id = self._require_agent_id()
        if isinstance(agent_id, ServiceResult):
            return agent_id
        if self.network_status != "online":
            return self._failure("Join the network first")
        return agent_id

    def _success(self, message: str = "", **data: Any) -> ServiceResult:
        self.last_error = ""
        return ServiceResult(True, message, data)

    def _failure(self, message: str) -> ServiceResult:
        self.last_error = message
        return ServiceResult(False, message)

    def _record_callback_error(self, message: str) -> None:
        self.last_error = message
        self._logger.error("Gateway callback failed: %s", message)
