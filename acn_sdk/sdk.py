from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import SDKConfig
from .credential.credential_issuer import CredentialIssuer
from .crypto import ensure_ec_keypair, load_public_key_pem, sign_timestamp
from .identity.identity_manager import IdentityManager
from .logging_config import setup_logging
from .logging_utils import format_json_for_log
from .reporting.pipeline_log_reporter import PipelineLogReporter
from .models import (
    AgentCardRequest,
    AgentDiscoveryRequest,
    AgentInfoQueryRequest,
    DeregisterRequest,
    AgentInfo,
    OwnerAgentsQueryRequest,
    TaskExecutionRequest,
    TaskTerminationRequest,
    WebSocketMessage,
)
from .network.http_client import HttpClient
from .network.moq_client import MoQClient
from .network.websocket_client import WebSocketClient
from .task.task_manager import TaskManager

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
NETWORK_ONLINE = "online"
NETWORK_OFFLINE = "offline"
TASK_PROCESSING = "Processing"
TASK_TERMINATED = "Terminated"


class AcnSDK:
    def __init__(
        self,
        agent_name: str,
        config_path: str | Path | None = None,
    ) -> None:
        self.config_path = Path(config_path).expanduser().resolve() if config_path is not None else DEFAULT_CONFIG_PATH
        self.config = SDKConfig.load(self.config_path)
        self.agent_name = agent_name
        self.on_task_collaboration_request = None
        self.on_discover_result_received = None
        self.on_task_start_command = None
        self.on_message_received = None
        self.credential_issuer = CredentialIssuer()
        self.http_client: HttpClient | None = None
        self.websocket_client: WebSocketClient | None = None
        self.moq_pub_client: MoQClient | None = None
        self.moq_sub_client: MoQClient | None = None
        self.pipeline_log_reporter: PipelineLogReporter | None = None
        self.task_manager: TaskManager | None = None
        self.network_status = NETWORK_OFFLINE
        self._published_tracks: set[str] = set()
        self._subscribed_tracks: set[str] = set()
        self._task_registry: dict[str, dict[str, Any]] = {}
        self._network_listener_stop = threading.Event()
        self._network_listener_thread: threading.Thread | None = None

        self._apply_config()
        self._logger.info("AcnSDK initialized for agent=%s, network_status=%s", agent_name, self.network_status)
        self._logger.info(
            "SDK network endpoints acn_agent=%s ws=%s moq=%s web_ui=%s",
            self.config.network.acn_agent_port,
            self.config.network.agent_gw_ws_port,
            self.config.network.agent_gw_moq_port,
            self.config.network.web_ui_port,
        )

    def register_callbacks(
        self,
        *,
        on_task_collaboration_request: Any | None = None,
        on_discover_result_received: Any | None = None,
        on_task_start_command: Any | None = None,
        on_message_received: Any | None = None,
    ) -> tuple[bool, str]:
        try:
            if on_task_collaboration_request is not None:
                self.on_task_collaboration_request = on_task_collaboration_request
            if on_discover_result_received is not None:
                self.on_discover_result_received = on_discover_result_received
            if on_task_start_command is not None:
                self.on_task_start_command = on_task_start_command
            if on_message_received is not None:
                self.on_message_received = on_message_received
            return (True, "OK")
        except Exception as exc:
            self._logger.exception("Failed to register callbacks.")
            return (False, str(exc))

    def reload_config(self) -> tuple[bool, str]:
        try:
            if any(
                client is not None
                for client in (
                    self.websocket_client,
                    self.moq_pub_client,
                    self.moq_sub_client,
                    self.task_manager,
                )
            ):
                self.disconnect_all()

            self.config = SDKConfig.load(self.config_path)
            self._apply_config()
            self._logger.info("Reloaded configuration from %s", self.config_path)
            return (True, "OK")
        except Exception as exc:
            self._logger.exception("Failed to reload configuration from %s.", self.config_path)
            return (False, str(exc))

    def register_agent_info(self, agent_info: AgentInfo) -> tuple[bool, str]:
        try:
            timestamp = self._utc_timestamp()
            payload = {
                "owner": agent_info.owner,
                "name": agent_info.name,
                "public_key": load_public_key_pem(self.config.storage.public_key_file),
                "description": agent_info.description,
                "timestamp": timestamp,
                "metadata": agent_info.metadata,
            }
            payload["signature"] = sign_timestamp(self.config.storage.private_key_file, timestamp)
            payload["signature_encoding"] = "base64"

            self._report_pipeline_log(
                protocol="HTTP",
                destination="ACN Agent",
                method="POST",
                url="/idm/v1/identity-applications",
                headers={"Content-Type": "application/json"},
                abstract="Register agent identity",
                content=payload,
            )
            response = self.http_client.register_agent_info(payload)
            agent_id = response["agent_id"]
            vc0 = response["vc0"]
            self.identity_manager.set_identity(
                agent_id=agent_id,
                vc0=vc0,
                agent_name=agent_info.name,
                owner=agent_info.owner,
                priority=agent_info.priority,
                metadata=agent_info.metadata,
            )
            self._logger.info("Agent registered. agent_id=%s response=\n%s", agent_id, format_json_for_log(response))
            return (True, agent_id)
        except Exception as exc:
            self._logger.exception("Failed to register agent info for agent=%s.", agent_info.name)
            return (False, str(exc))

    def register_agent_attribute(self, agent_id: str, capability: list[str] | str) -> tuple[bool, str]:
        try:
            if not self.identity_manager.agent_id or not self.identity_manager.vc0:
                raise RuntimeError("Robot identity must be registered before capabilities.")
            if not agent_id:
                raise ValueError("agent_id must not be empty.")
            if agent_id != self.identity_manager.agent_id:
                raise ValueError("The supplied agent_id does not match this device.")

            capability_list = [capability] if isinstance(capability, str) else capability
            new_capabilities = self.identity_manager.get_pending_capabilities(capability_list)
            if new_capabilities:
                capability_vcs = self.credential_issuer.fetch_capacity_vc(
                    agent_id,
                    new_capabilities,
                    self.identity_manager.agent_name or self.agent_name,
                )
                self.identity_manager.set_capability_vcs(capability_vcs)

            vc_list = [self.identity_manager.vc0, *self.identity_manager.capability_vcs]

            timestamp = self._utc_timestamp()
            payload = AgentCardRequest(
                agent_id=agent_id,
                priority=self.identity_manager.priority or 0,
                timestamp=timestamp,
                signature=sign_timestamp(self.config.storage.private_key_file, timestamp),
                vc_list=vc_list,
            )
            if self.http_client is None:
                raise RuntimeError("HTTP client is not initialized.")
            self._report_pipeline_log(
                protocol="HTTP",
                destination="ACN Agent",
                method="POST",
                url="/arf/v1/agent-cards",
                headers={"Content-Type": "application/json"},
                abstract="Register agent capabilities",
                content=payload.model_dump(mode="json"),
            )
            response = self.http_client.register_agent_attribute(payload)
            self._logger.info("Robot attribute registered. response=\n%s", format_json_for_log(response))
            return (True, self._stringify_result(response))
        except Exception as exc:
            self._logger.exception("Failed to register robot attribute for agent_id=%s.", agent_id)
            return (False, str(exc))

    def query_agent_id(self, agent_name: str, owner: str) -> tuple[bool, str]:
        try:
            agent_id = self.identity_manager.query_agent_id(agent_name, owner)
            self._logger.info(
                "Queried robot identity agent_name=%s owner=%s result=%s",
                agent_name,
                owner,
                agent_id,
            )
            return (agent_id is not None, agent_id or "")
        except Exception as exc:
            self._logger.exception("Failed to query robot identity agent_name=%s owner=%s.", agent_name, owner)
            return (False, str(exc))

    def query_agent_info(self, agent_id: str) -> tuple[bool, str]:
        try:
            if not agent_id:
                raise ValueError("agent_id must not be empty.")
            local_agent_id = self.identity_manager.agent_id
            if local_agent_id == agent_id:
                result = self._build_local_agent_info()
                self._logger.info("Queried local agent info agent_id=%s result=\n%s", agent_id, format_json_for_log(result))
                return (True, self._stringify_result(result))

            if self.http_client is None:
                raise RuntimeError("HTTP client is not initialized.")
            request = AgentInfoQueryRequest(agent_id=agent_id)
            self._report_pipeline_log(
                protocol="HTTP",
                destination="ARF",
                method="POST",
                url="/arf/v1/agent-info",
                headers={"Content-Type": "application/json"},
                abstract="Query agent info",
                content=request.model_dump(mode="json"),
            )
            response = self.http_client.query_agent_info(request)
            self._logger.info("Queried remote agent info agent_id=%s result=\n%s", agent_id, format_json_for_log(response))
            return (True, self._stringify_result(response))
        except Exception as exc:
            self._logger.exception("Failed to query agent info for agent_id=%s.", agent_id)
            return (False, str(exc))

    def query_agent_list(self, owner_name: str) -> tuple[bool, str]:
        try:
            if not owner_name:
                raise ValueError("owner_name must not be empty.")
            if self.http_client is None:
                raise RuntimeError("HTTP client is not initialized.")
            request = OwnerAgentsQueryRequest(owner=owner_name)
            self._report_pipeline_log(
                protocol="HTTP",
                destination="ACN Agent",
                method="POST",
                url="/acn-agent/v1/owner-agents",
                headers={"Content-Type": "application/json"},
                abstract="Query owner agent list",
                content=request.model_dump(mode="json"),
            )
            response = self.http_client.query_agent_list(request)
            self._logger.info("Queried agent list owner=%s result=\n%s", owner_name, format_json_for_log(response))
            return (True, self._stringify_result(response))
        except Exception as exc:
            self._logger.exception("Failed to query agent list for owner=%s.", owner_name)
            return (False, str(exc))

    def deregister_agent(self, agent_id: str, reason: str) -> tuple[bool, str]:
        try:
            if self.identity_manager.agent_id != agent_id:
                raise ValueError("The supplied agent_id does not match this device.")
            if self._has_processing_tasks():
                raise RuntimeError("Cannot deregister while tasks are still processing.")

            timestamp = self._utc_timestamp()
            request = DeregisterRequest(
                agent_id=agent_id,
                reason=reason,
                timestamp=timestamp,
                signature=sign_timestamp(self.config.storage.private_key_file, timestamp),
            )
            self._report_pipeline_log(
                protocol="HTTP",
                destination="ACN Agent",
                method="POST",
                url="/acn-agent/v1/agent-deletions",
                headers={"Content-Type": "application/json"},
                abstract="Deregister agent",
                content=request.model_dump(mode="json"),
            )
            response = self.http_client.deregister_agent(request)

            if self.network_status == NETWORK_ONLINE and self.websocket_client is not None:
                disconnection_message = self._build_ws_message(
                    "DISCONNECTION",
                    {"src_agent_id": agent_id},
                )
                self._report_pipeline_log(
                    protocol="WebSocket",
                    destination="Agent GW",
                    method="SEND",
                    url=self.config.network.agent_gw_ws_url,
                    headers={},
                    abstract="WebSocket disconnection",
                    content=disconnection_message,
                    task_id=None,
                )
                self.websocket_client.send_json(
                    disconnection_message
                )
            self._clear_identity_and_network_state(clear_task_registry=True)
            self._logger.info("Robot deregistered. response=\n%s", format_json_for_log(response))
            return (True, self._stringify_result(response))
        except Exception as exc:
            self._logger.exception("Failed to deregister robot agent_id=%s.", agent_id)
            return (False, str(exc))

    def join_network(self, agent_id: str) -> tuple[bool, str]:
        try:
            self._require_local_agent(agent_id)
            if self.network_status == NETWORK_ONLINE:
                raise RuntimeError("Robot is already online.")

            self.websocket_client = self._create_websocket_client()
            self.moq_pub_client = self._create_moq_client("publisher")
            self.moq_sub_client = self._create_moq_client("subscriber")
            self.task_manager = TaskManager()

            try:
                self.websocket_client.connect()
                setup_message = self._build_ws_message(
                    "SETUP",
                    {"src_agent_id": agent_id},
                )
                self._report_pipeline_log(
                    protocol="WebSocket",
                    destination="Agent GW",
                    method="SEND",
                    url=self.config.network.agent_gw_ws_url,
                    headers={},
                    abstract="WebSocket setup handshake",
                    content=setup_message,
                )
                self.websocket_client.send_json(
                    setup_message
                )
                response = self.websocket_client.receive_json()
                if response.get("type") != "SETUP" or response.get("payload", {}).get("status") != "OK":
                    raise RuntimeError(f"Unexpected setup response: {response}")
                self.moq_pub_client.connect()
                self.moq_sub_client.connect()
            except Exception:
                self.disconnect_all(close_http=False)
                raise

            self.network_status = NETWORK_ONLINE
            self._start_network_listener()
            self._logger.info("Network join successful for agent_id=%s", agent_id)
            return (True, "")
        except Exception as exc:
            self._logger.exception("Failed to join network for agent_id=%s.", agent_id)
            return (False, str(exc))

    def logout_network(self, agent_id: str) -> tuple[bool, str]:
        try:
            self._require_local_agent(agent_id)
            if self.network_status != NETWORK_ONLINE:
                raise RuntimeError("Robot is not online.")
            if self._has_processing_tasks():
                raise RuntimeError("Cannot logout while tasks are still processing.")
            if self.websocket_client is not None:
                disconnection_message = self._build_ws_message(
                    "DISCONNECTION",
                    {"src_agent_id": agent_id},
                )
                self._report_pipeline_log(
                    protocol="WebSocket",
                    destination="Agent GW",
                    method="SEND",
                    url=self.config.network.agent_gw_ws_url,
                    headers={},
                    abstract="WebSocket disconnection",
                    content=disconnection_message,
                )
                self.websocket_client.send_json(
                    disconnection_message
                )
            self.disconnect_all(close_http=False, clear_task_registry=False)
            return (True, "")
        except Exception as exc:
            self._logger.exception("Failed to logout network for agent_id=%s.", agent_id)
            return (False, str(exc))

    def query_network_status(self, agent_id: str) -> tuple[bool, str]:
        try:
            self._require_local_agent(agent_id)
            return (True, self.network_status)
        except Exception as exc:
            self._logger.exception("Failed to query network status for agent_id=%s.", agent_id)
            return (False, str(exc))

    def query_task_status(self, agent_id: str, task_id: str) -> tuple[bool, str]:
        try:
            self._require_local_agent(agent_id)
            task_entry = self._task_registry.get(task_id)
            if not isinstance(task_entry, dict):
                raise KeyError(f"Task {task_id} is not found.")
            task_detail = self._summarize_task_entry(task_id, task_entry)
            return (True, self._stringify_result(task_detail))
        except Exception as exc:
            self._logger.exception("Failed to query task status for agent_id=%s task_id=%s.", agent_id, task_id)
            return (False, str(exc))

    def query_task_list(self, agent_id: str) -> tuple[bool, str]:
        try:
            self._require_local_agent(agent_id)
            task_list = [self._summarize_task_entry(task_id, task_entry) for task_id, task_entry in self._task_registry.items()]
            return (True, self._stringify_result(task_list))
        except Exception as exc:
            self._logger.exception("Failed to query task list for agent_id=%s.", agent_id)
            return (False, str(exc))

    def request_task_execution(self, agent_id: str, task_info: str, task_id: str | None = None) -> tuple[bool, str]:
        try:
            self._require_online_agent(agent_id)
            task_id = task_id or self._generate_task_id()
            request = TaskExecutionRequest(
                agent_id=agent_id,
                task_id=task_id,
                description=task_info,
                timestamp=self._utc_timestamp(),
            )
            self._report_pipeline_log(
                protocol="HTTP",
                destination="ACN Agent",
                method="POST",
                url="/acn-agent/v1/task-executions",
                headers={"Content-Type": "application/json"},
                abstract="Request task execution",
                content=request.model_dump(mode="json"),
                task_id=task_id,
            )
            response = self.http_client.request_task_execution(request)
            self._task_registry[task_id] = {
                "description": task_info,
                "status": TASK_PROCESSING,
                "published_tracks": set(),
                "subscribed_tracks": set(),
            }
            self._logger.info("Task execution requested. task_id=%s response=\n%s", task_id, format_json_for_log(response))
            return (True, task_id)
        except Exception as exc:
            self._logger.exception("Failed to request task execution for agent_id=%s.", agent_id)
            return (False, str(exc))

    def request_terminate_task(
        self,
        agent_id: str,
        task_id: str,
        reason: str = "",
        force: bool = False,
    ) -> tuple[bool, str]:
        try:
            self._require_online_agent(agent_id)
            task_context = self._task_registry.get(task_id)
            if task_context is None or task_context.get("status") != TASK_PROCESSING:
                raise RuntimeError("Task is not processing.")
            request = TaskTerminationRequest(
                agent_id=agent_id,
                task_id=task_id,
                reason=reason,
                timestamp=self._utc_timestamp(),
                force=force,
            )
            self._report_pipeline_log(
                protocol="HTTP",
                destination="ACN Agent",
                method="POST",
                url="/acn-agent/v1/task-execution-terminations",
                headers={"Content-Type": "application/json"},
                abstract="Request task termination",
                content=request.model_dump(mode="json"),
                task_id=task_id,
            )
            response = self.http_client.request_terminate_task(request)
            self._stop_task_tracks(task_id)
            if task_id in self._task_registry:
                self._task_registry[task_id]["status"] = TASK_TERMINATED
            self._logger.info("Task termination requested. task_id=%s response=\n%s", task_id, format_json_for_log(response))
            return (True, self._stringify_result(response))
        except Exception as exc:
            self._logger.exception("Failed to request task termination for task_id=%s.", task_id)
            return (False, str(exc))

    def task_info_report(self, agent_id: str, task_id: str, topic: str, message_info: bytes) -> tuple[bool, str]:
        try:
            self._require_online_agent(agent_id)
            namespace = f"/{task_id}/{agent_id}"
            track_key = self._track_key(namespace, topic)

            if self.moq_pub_client is None:
                raise RuntimeError("MoQ publisher is not connected. Call join_network() first.")

            if track_key not in self._published_tracks:
                moq_url = f"moq://{self.config.network.network_ip}:{self.config.network.agent_gw_moq_port}"
                self._report_pipeline_log(
                    protocol="MoQ",
                    destination="Agent GW",
                    method="PUBLISH",
                    url=moq_url,
                    headers={},
                    abstract="Publish MoQ track",
                    content={"namespace": namespace, "track": topic},
                    task_id=task_id,
                )
                self.moq_pub_client.publish(namespace, topic)
                if self.websocket_client is None:
                    raise RuntimeError("WebSocket is not connected.")
                publish_track_message = self._build_ws_message(
                    "PUBLISH_TRACK",
                    {
                        "src_agent_id": agent_id,
                        "task_id": task_id,
                        "track_list": [{"namespace": namespace, "track": topic}],
                    },
                )
                self._report_pipeline_log(
                    protocol="WebSocket",
                    destination="Agent GW",
                    method="SEND",
                    url=self.config.network.agent_gw_ws_url,
                    headers={},
                    abstract="Announce MoQ published track",
                    content=publish_track_message,
                    task_id=task_id,
                )
                self.websocket_client.send_json(
                    publish_track_message
                )
                self._published_tracks.add(track_key)
                self._track_task_published(task_id, track_key)

            self._report_pipeline_log(
                protocol="MoQ",
                destination="Agent GW",
                method="SEND",
                url=f"moq://{self.config.network.network_ip}:{self.config.network.agent_gw_moq_port}",
                headers={},
                abstract="Send MoQ object",
                content=message_info,
                task_id=task_id,
            )
            self.moq_pub_client.send_object(namespace, topic, message_info)
            self._logger.info(
                "Task info reported. agent_id=%s task_id=%s topic=%s payload_size=%s",
                agent_id,
                task_id,
                topic,
                len(message_info),
            )
            return (True, self._stringify_result({"task_id": task_id, "topic": topic}))
        except Exception as exc:
            self._logger.exception("Failed to report task info for task_id=%s topic=%s.", task_id, topic)
            return (False, str(exc))

    def request_task_collaboration(
        self,
        agent_id: str,
        task_id: str,
        required_capabilities: str | list[str],
    ) -> tuple[bool, str]:
        try:
            self._require_online_agent(agent_id)
            capability_list = [required_capabilities] if isinstance(required_capabilities, str) else required_capabilities
            request = AgentDiscoveryRequest(
                task_id=task_id,
                agent_id=agent_id,
                required_capabilities=capability_list,
                timestamp=self._utc_timestamp(),
            )
            if self.http_client is None:
                raise RuntimeError("HTTP client is not initialized.")
            self._report_pipeline_log(
                protocol="HTTP",
                destination="ARF",
                method="POST",
                url="/arf/v1/agent-discoveries",
                headers={"Content-Type": "application/json"},
                abstract="Request task collaboration",
                content=request.model_dump(mode="json"),
                task_id=task_id,
            )
            response = self.http_client.request_task_collaboration(request)
            self._logger.info("Task collaboration requested. task_id=%s response=\n%s", task_id, format_json_for_log(response))
            return (True, self._stringify_result(response))
        except Exception as exc:
            self._logger.exception("Failed to request task collaboration for task_id=%s.", task_id)
            return (False, str(exc))

    def accept_task_collaboration(
        self,
        agent_id: str,
        task_id: str,
    ) -> tuple[bool, str]:
        try:
            self._require_online_agent(agent_id)
            if self.websocket_client is None:
                raise RuntimeError("WebSocket is not connected.")
            task_context = self._task_registry.get(task_id, {})
            dst_agent_id = task_context.get("requesting_agent_id")
            if not dst_agent_id:
                raise ValueError(f"requesting_agent_id is not available for task_id={task_id}.")
            message = self._build_ws_message(
                "TASK_ACCEPT_COLLABORATION",
                {
                    "src_agent_id": agent_id,
                    "dst_agent_id": dst_agent_id,
                    "task_id": task_id,
                    "result": "OK",
                },
            )
            self._report_pipeline_log(
                protocol="WebSocket",
                destination="Agent GW",
                method="SEND",
                url=self.config.network.agent_gw_ws_url,
                headers={},
                abstract="Accept task collaboration",
                content=message,
                task_id=task_id,
            )
            self.websocket_client.send_json(message)
            self._logger.info("Task collaboration accepted. task_id=%s dst_agent_id=%s", task_id, dst_agent_id)
            return (True, task_id)
        except Exception as exc:
            self._logger.exception("Failed to accept task collaboration for task_id=%s.", task_id)
            return (False, str(exc))

    def start_task_collaboration(
        self,
        agent_id: str,
        dst_agent_id: str,
        task_id: str,
        task_description: str,
    ) -> tuple[bool, str]:
        try:
            self._require_online_agent(agent_id)
            if self.websocket_client is None:
                raise RuntimeError("WebSocket is not connected.")
            message = self._build_ws_message(
                "START_TASK",
                {
                    "src_agent_id": agent_id,
                    "dst_agent_id": dst_agent_id,
                    "task_id": task_id,
                    "task_description": task_description,
                },
            )
            self._report_pipeline_log(
                protocol="WebSocket",
                destination="Agent GW",
                method="SEND",
                url=self.config.network.agent_gw_ws_url,
                headers={},
                abstract="Start task collaboration",
                content=message,
                task_id=task_id,
            )
            self.websocket_client.send_json(message)
            self._logger.info(
                "Start task message sent. src_agent_id=%s dst_agent_id=%s task_id=%s",
                agent_id,
                dst_agent_id,
                task_id,
            )
            return (True, self._stringify_result({"task_id": task_id, "dst_agent_id": dst_agent_id}))
        except Exception as exc:
            self._logger.exception("Failed to start task task_id=%s dst_agent_id=%s.", task_id, dst_agent_id)
            return (False, str(exc))

    def handle_network_message(self, message: str | dict[str, Any]) -> tuple[bool, str]:
        try:
            parsed_message = json.loads(message) if isinstance(message, str) else message
            envelope = WebSocketMessage.model_validate(parsed_message)
            message_type = envelope.type
            payload = envelope.payload
            self._logger.info("Handling network message type=%s payload=\n%s", message_type, format_json_for_log(payload))

            if message_type == "SUBSCRIBE_TRACK":
                self._handle_subscribe_track(payload)
            elif message_type == "CLEAR":
                self._clear_identity_and_network_state(clear_task_registry=True, force_stop_processing_tasks=True)
            elif message_type == "TASK_REQUEST_COLLABORATION":
                task_id = payload.get("task_id")
                if task_id:
                    self._task_registry[task_id] = {
                        **self._task_registry.get(task_id, {}),
                        "requesting_agent_id": payload.get("src_agent_id"),
                        "collaboration_request": payload,
                    }
                self._dispatch_message_callback("on_task_collaboration_request", self.on_task_collaboration_request, payload)
            elif message_type == "DISCOVER_RESULT":
                self._dispatch_message_callback("on_discover_result_received", self.on_discover_result_received, payload)
            elif message_type == "TASK_ASSIGNED":
                self._handle_task_assigned(payload)
            elif message_type == "START_TASK":
                self._dispatch_message_callback("on_task_start_command", self.on_task_start_command, payload)

            return (True, self._stringify_result(parsed_message))
        except Exception as exc:
            self._logger.exception("Failed to handle network message.")
            return (False, str(exc))

    def clear_all(self) -> tuple[bool, str]:
        try:
            self._clear_identity_and_network_state(clear_task_registry=True, force_stop_processing_tasks=True)
            self._logger.info("Cleared all SDK state.")
            return (True, "")
        except Exception as exc:
            self._logger.exception("Failed to clear SDK state.")
            return (False, str(exc))

    def disconnect_all(self, close_http: bool = True, clear_task_registry: bool = False) -> tuple[bool, str]:
        try:
            self._stop_network_listener()
            if close_http:
                if self.http_client is not None:
                    self.http_client.close()
                if self.pipeline_log_reporter is not None:
                    self.pipeline_log_reporter.close()
            if self.websocket_client is not None:
                self.websocket_client.disconnect()
                self.websocket_client = None
            if self.moq_pub_client is not None:
                self.moq_pub_client.disconnect()
                self.moq_pub_client = None
            if self.moq_sub_client is not None:
                self.moq_sub_client.disconnect()
                self.moq_sub_client = None
            if self.task_manager is not None:
                self.task_manager.stop_all()
                self.task_manager = None
            self._clear_track_state(clear_task_registry=clear_task_registry)
            self.network_status = NETWORK_OFFLINE
            self._logger.info("Network state changed to %s", self.network_status)
            return (True, NETWORK_OFFLINE)
        except Exception as exc:
            self._logger.exception("Failed to disconnect network components.")
            return (False, str(exc))

    def _apply_config(self) -> None:
        setup_logging(self.config.log_level, self.config.storage.log_dir)
        self._logger = logging.getLogger(self.__class__.__name__)
        self.identity_manager = IdentityManager(self.config.storage.identity_file)
        self.http_client = HttpClient(self.config.network.acn_agent_url, self.config.network.arf_url)
        self.pipeline_log_reporter = PipelineLogReporter(self.config.network.web_ui_url)
        ensure_ec_keypair(
            self.config.storage.private_key_file,
            self.config.storage.public_key_file,
        )

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _create_websocket_client(self) -> WebSocketClient:
        return WebSocketClient(self.config.network.agent_gw_ws_url)

    def _create_moq_client(self, role: str) -> MoQClient:
        return MoQClient(
            host=self.config.network.network_ip,
            remote_port=self.config.network.agent_gw_moq_port,
            role=role,
            on_object_received=self._handle_moq_object_received if role == "subscriber" else None,
        )

    def _handle_subscribe_track(self, payload: dict[str, Any]) -> None:
        if self.moq_sub_client is None:
            raise RuntimeError("MoQ subscriber is not connected. Call join_network() first.")
        local_agent_id = self.identity_manager.agent_id or self.agent_name
        task_id = payload.get("task_id")
        for track_info in payload.get("track_list", []):
            namespace = track_info["namespace"]
            track = track_info["track"]
            track_key = self._track_key(namespace, track)
            if track_key in self._subscribed_tracks or track_key in self._published_tracks:
                continue
            self._report_pipeline_log(
                protocol="MoQ",
                destination="Agent GW",
                method="SUBSCRIBE",
                url=f"moq://{self.config.network.network_ip}:{self.config.network.agent_gw_moq_port}",
                headers={},
                abstract="Subscribe MoQ track",
                content={"namespace": namespace, "track": track, "subscriber_id": local_agent_id},
                task_id=payload.get("task_id"),
            )
            self.moq_sub_client.subscribe(namespace, track, local_agent_id)
            self._subscribed_tracks.add(track_key)
            if isinstance(task_id, str) and task_id:
                self._track_task_subscribed(task_id, track_key)

    def _handle_task_assigned(self, payload: dict[str, Any]) -> None:
        agent_id = self.identity_manager.agent_id
        if not agent_id:
            raise RuntimeError("Local agent_id is not available in identity_manager.")

        assigned_agents = payload.get("assigned_agents")
        if isinstance(assigned_agents, list) and assigned_agents and agent_id not in assigned_agents:
            self._logger.info(
                "Ignoring TASK_ASSIGNED for unassigned local agent_id=%s assigned_agents=%s",
                agent_id,
                assigned_agents,
            )
            return

        task_description = payload.get("task_description")
        if not isinstance(task_description, str) or not task_description.strip():
            raise ValueError("TASK_ASSIGNED payload.task_description must be a non-empty string.")

        result, task_id = self.request_task_execution(agent_id, task_description, task_id=None)
        if not result:
            raise RuntimeError(f"Failed to request task execution for TASK_ASSIGNED: {task_id}")
        self._logger.info(
            "TASK_ASSIGNED triggered task execution. agent_id=%s task_description=%s generated_task_id=%s",
            agent_id,
            task_description,
            task_id,
        )

    def _handle_moq_object_received(self, namespace: str, track: str, payload: bytes) -> None:
        if self.on_message_received is not None:
            self.on_message_received(namespace, track, payload)

    def _build_local_agent_info(self) -> dict[str, Any]:
        agent_id = self.identity_manager.agent_id
        if not agent_id:
            raise RuntimeError("Local agent_id is not available in identity_manager.")
        return {
            "agent_id": agent_id,
            "agent_name": self.identity_manager.agent_name or self.agent_name,
            "agent_status": self.network_status,
            "agent_capabilities": list(self.identity_manager.capability_names),
            "priority": self.identity_manager.priority or 0,
        }

    def _start_network_listener(self) -> None:
        if self.websocket_client is None:
            raise RuntimeError("WebSocket is not connected.")
        if self._network_listener_thread is not None and self._network_listener_thread.is_alive():
            return
        self._network_listener_stop = threading.Event()
        self._network_listener_thread = threading.Thread(
            target=self._network_listener_loop,
            name=f"AcnSDKNetworkListener-{self.agent_name}",
            daemon=True,
        )
        self._network_listener_thread.start()
        self._logger.info("Background network listener started.")

    def _stop_network_listener(self) -> None:
        self._network_listener_stop.set()
        if self.websocket_client is not None:
            self.websocket_client.disconnect()
        thread = self._network_listener_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._network_listener_thread = None
        self._network_listener_stop.clear()

    def _network_listener_loop(self) -> None:
        while not self._network_listener_stop.is_set():
            websocket_client = self.websocket_client
            if websocket_client is None:
                break
            try:
                message = websocket_client.receive_json()
            except Exception:
                if self._network_listener_stop.is_set():
                    break
                self._logger.exception("Background network listener stopped after websocket receive failure.")
                break

            try:
                self.handle_network_message(message)
            except Exception:
                self._logger.exception("Failed to handle background network message: %s", format_json_for_log(message))

    def _require_local_agent(self, agent_id: str) -> None:
        if not agent_id:
            raise ValueError("agent_id must not be empty.")
        if self.identity_manager.agent_id != agent_id:
            raise ValueError("The supplied agent_id does not match this device.")

    def _require_online_agent(self, agent_id: str) -> None:
        self._require_local_agent(agent_id)
        if self.network_status != NETWORK_ONLINE:
            raise RuntimeError("Robot must be online before performing task operations.")

    def _clear_track_state(self, *, clear_task_registry: bool = False) -> None:
        self._published_tracks.clear()
        self._subscribed_tracks.clear()
        if clear_task_registry:
            self._task_registry.clear()
            return
        for task_entry in self._task_registry.values():
            if isinstance(task_entry, dict):
                task_entry["published_tracks"] = set()
                task_entry["subscribed_tracks"] = set()

    def _clear_identity_and_network_state(
        self,
        *,
        clear_task_registry: bool = False,
        force_stop_processing_tasks: bool = False,
    ) -> None:
        if force_stop_processing_tasks:
            for task_id in self._get_processing_task_ids():
                self._stop_task_tracks(task_id)
                if task_id in self._task_registry:
                    self._task_registry[task_id]["status"] = TASK_TERMINATED
        self.identity_manager.clear()
        self.disconnect_all(close_http=False, clear_task_registry=clear_task_registry)

    def _get_processing_task_ids(self) -> list[str]:
        return [
            task_id
            for task_id, task_entry in self._task_registry.items()
            if isinstance(task_entry, dict) and task_entry.get("status") == TASK_PROCESSING
        ]

    def _has_processing_tasks(self) -> bool:
        return bool(self._get_processing_task_ids())

    def _stop_task_tracks(self, task_id: str) -> None:
        task_entry = self._task_registry.get(task_id)
        if not isinstance(task_entry, dict):
            return
        published_tracks = task_entry.get("published_tracks")
        if isinstance(published_tracks, set):
            for track_key in list(published_tracks):
                namespace, track = self._split_track_key(track_key)
                if self.moq_pub_client is not None:
                    try:
                        self.moq_pub_client.unpublish(namespace, track)
                    except Exception:
                        self._logger.exception("Failed to unpublish task_id=%s track=%s", task_id, track_key)
                self._published_tracks.discard(track_key)
                published_tracks.discard(track_key)
        subscribed_tracks = task_entry.get("subscribed_tracks")
        if isinstance(subscribed_tracks, set):
            for track_key in list(subscribed_tracks):
                namespace, track = self._split_track_key(track_key)
                if self.moq_sub_client is not None:
                    try:
                        self.moq_sub_client.unsubscribe(namespace, track, self.identity_manager.agent_id or self.agent_name)
                    except Exception:
                        self._logger.exception("Failed to unsubscribe task_id=%s track=%s", task_id, track_key)
                self._subscribed_tracks.discard(track_key)
                subscribed_tracks.discard(track_key)

    def _track_task_published(self, task_id: str, track_key: str) -> None:
        task_entry = self._task_registry.get(task_id)
        if not isinstance(task_entry, dict):
            return
        task_entry.setdefault("published_tracks", set())
        published_tracks = task_entry.setdefault("published_tracks", set())
        if isinstance(published_tracks, set):
            published_tracks.add(track_key)

    def _track_task_subscribed(self, task_id: str, track_key: str) -> None:
        task_entry = self._task_registry.get(task_id)
        if not isinstance(task_entry, dict):
            return
        task_entry.setdefault("subscribed_tracks", set())
        subscribed_tracks = task_entry.setdefault("subscribed_tracks", set())
        if isinstance(subscribed_tracks, set):
            subscribed_tracks.add(track_key)

    @staticmethod
    def _summarize_task_entry(task_id: str, task_entry: dict[str, Any]) -> dict[str, Any]:
        published_tracks = task_entry.get("published_tracks", set())
        subscribed_tracks = task_entry.get("subscribed_tracks", set())
        return {
            "task_id": task_id,
            "description": task_entry.get("description"),
            "status": task_entry.get("status"),
            "requesting_agent_id": task_entry.get("requesting_agent_id"),
            "published_tracks": sorted(published_tracks) if isinstance(published_tracks, set) else [],
            "subscribed_tracks": sorted(subscribed_tracks) if isinstance(subscribed_tracks, set) else [],
        }

    @staticmethod
    def _split_track_key(track_key: str) -> tuple[str, str]:
        namespace, track = track_key.split("::", 1)
        return namespace, track

    def _build_ws_message(self, message_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return WebSocketMessage(
            type=message_type,
            timestamp=self._utc_timestamp(),
            payload=payload,
        ).model_dump(mode="json")

    def _report_pipeline_log(
        self,
        *,
        protocol: str,
        destination: str,
        method: str,
        url: str,
        headers: dict[str, str] | None,
        abstract: str,
        content: Any,
        task_id: str | None = None,
    ) -> None:
        if self.pipeline_log_reporter is None:
            return
        self.pipeline_log_reporter.report(
            source="ACN SDK",
            destination=destination,
            protocol=protocol,
            method=method,
            url=url,
            headers=headers,
            abstract=abstract,
            content=content,
            task_id=task_id,
        )

    @staticmethod
    def _stringify_result(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)

    @staticmethod
    def _dispatch_message_callback(callback_name: str, callback: Any | None, payload: dict[str, Any]) -> None:
        if callback is None:
            return
        try:
            callback(payload)
        except TypeError as exc:
            raise TypeError(f"{callback_name} must accept a single payload argument.") from exc

    @staticmethod
    def _generate_task_id() -> str:
        return f"task-{secrets.token_hex(3)[:5]}"

    @staticmethod
    def _track_key(namespace: str, track: str) -> str:
        return f"{namespace}::{track}"
