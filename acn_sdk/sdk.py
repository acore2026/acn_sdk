from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import SDKConfig
from .credential.credential_issuer import CredentialIssuer, HUAWEI_ISSUER_DID
from .crypto import ensure_ec_keypair, load_public_key_pem, sign_timestamp
from .identity.identity_manager import IdentityManager
from .logging_config import setup_logging
from .logging_utils import format_json_for_log
from .models import (
    AgentCardRequest,
    AgentDiscoveryRequest,
    DeregisterRequest,
    RobotInfo,
    TaskExecutionRequest,
    TaskTerminationRequest,
    WebSocketMessage,
)
from .network.http_client import HttpClient
from .network.moq_client import MoQClient
from .network.websocket_client import WebSocketClient
from .task.task_manager import TaskManager

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


class AcnSDK:
    def __init__(
        self,
        robot_name: str,
        issuer_id: str = HUAWEI_ISSUER_DID,
        config_path: str | Path | None = None,
        on_message_received: Any | None = None,
        on_task_collaboration_request: Any | None = None,
        on_discover_result_received: Any | None = None,
        on_task_start_command: Any | None = None,
        on_moq_message_received: Any | None = None,
    ) -> None:
        self.config_path = Path(config_path).expanduser().resolve() if config_path is not None else DEFAULT_CONFIG_PATH
        self.config = SDKConfig.load(self.config_path)
        self.robot_name = robot_name
        self.issuer_id = issuer_id
        self.on_message_received = on_message_received
        self.on_task_collaboration_request = on_task_collaboration_request
        self.on_discover_result_received = on_discover_result_received
        self.on_task_start_command = on_task_start_command
        self.on_moq_message_received = on_moq_message_received
        self.credential_issuer = CredentialIssuer()
        self.http_client: HttpClient | None = None
        self.websocket_client: WebSocketClient | None = None
        self.moq_pub_client: MoQClient | None = None
        self.moq_sub_client: MoQClient | None = None
        self.task_manager: TaskManager | None = None
        self.network_status = "OFFLINE"
        self._published_tracks: set[str] = set()
        self._subscribed_tracks: set[str] = set()
        self._task_registry: dict[str, dict[str, Any]] = {}
        self._network_listener_stop = threading.Event()
        self._network_listener_thread: threading.Thread | None = None

        self._apply_config()
        self._logger.info("AcnSDK initialized for robot=%s, network_status=%s", robot_name, self.network_status)
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
        on_message_received: Any | None = None,
        on_task_collaboration_request: Any | None = None,
        on_discover_result_received: Any | None = None,
        on_task_start_command: Any | None = None,
        on_moq_message_received: Any | None = None,
    ) -> tuple[Any, ...]:
        try:
            if on_message_received is not None:
                self.on_message_received = on_message_received
            if on_task_collaboration_request is not None:
                self.on_task_collaboration_request = on_task_collaboration_request
            if on_discover_result_received is not None:
                self.on_discover_result_received = on_discover_result_received
            if on_task_start_command is not None:
                self.on_task_start_command = on_task_start_command
            if on_moq_message_received is not None:
                self.on_moq_message_received = on_moq_message_received
            return (True,)
        except Exception as exc:
            self._logger.exception("Failed to register callbacks.")
            return (False, str(exc))

    def reload_config(self) -> tuple[Any, ...]:
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
            return (True,)
        except Exception as exc:
            self._logger.exception("Failed to reload configuration from %s.", self.config_path)
            return (False, str(exc))

    def register_agent_info(self, robot_info: RobotInfo) -> tuple[Any, ...]:
        try:
            timestamp = self._utc_timestamp()
            payload = {
                "owner": robot_info.owner,
                "name": robot_info.name,
                "public_key": load_public_key_pem(self.config.storage.public_key_file),
                "description": robot_info.description,
                "timestamp": timestamp,
                "metadata": robot_info.metadata,
            }
            payload["signature"] = sign_timestamp(self.config.storage.private_key_file, timestamp)
            payload["signature_encoding"] = "base64"

            response = self.http_client.register_agent_info(payload)
            agent_id = response["agent_id"]
            vc0 = response["vc0"]
            self.identity_manager.set_identity(
                agent_id=agent_id,
                vc0=vc0,
                robot_name=robot_info.name,
                owner=robot_info.owner,
                priority=robot_info.priority,
                metadata=robot_info.metadata,
            )
            self._logger.info("Robot registered. agent_id=%s response=\n%s", agent_id, format_json_for_log(response))
            return (True, agent_id)
        except Exception as exc:
            self._logger.exception("Failed to register robot info for robot=%s.", robot_info.name)
            return (False, str(exc))

    def register_agent_attribute(self, agent_id: str, capability: list[str] | str) -> tuple[Any, ...]:
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
                    self.identity_manager.robot_name or self.robot_name,
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
            response = self.http_client.register_agent_attribute(payload)
            self._logger.info("Robot attribute registered. response=\n%s", format_json_for_log(response))
            return (True, response)
        except Exception as exc:
            self._logger.exception("Failed to register robot attribute for agent_id=%s.", agent_id)
            return (False, str(exc))

    def query_robot_id(self, robot_name: str, owner: str) -> tuple[Any, ...]:
        try:
            agent_id = self.identity_manager.query_robot_id(robot_name, owner)
            self._logger.info(
                "Queried robot identity robot_name=%s owner=%s result=%s",
                robot_name,
                owner,
                agent_id,
            )
            return (agent_id is not None, agent_id)
        except Exception as exc:
            self._logger.exception("Failed to query robot identity robot_name=%s owner=%s.", robot_name, owner)
            return (False, str(exc))

    def deregister_robot(self, agent_id: str, reason: str) -> tuple[Any, ...]:
        try:
            if self.identity_manager.agent_id != agent_id:
                raise ValueError("The supplied agent_id does not match this device.")

            timestamp = self._utc_timestamp()
            request = DeregisterRequest(
                agent_id=agent_id,
                reason=reason,
                timestamp=timestamp,
                signature=sign_timestamp(self.config.storage.private_key_file, timestamp),
            )
            response = self.http_client.deregister_robot(request)

            if self.network_status == "ONLINE" and self.websocket_client is not None:
                self.websocket_client.send_json(
                    self._build_ws_message(
                        "DISCONNECTION",
                        {"src_agent_id": agent_id},
                    )
                )
            self.identity_manager.clear()
            self.disconnect_all()
            self._logger.info("Robot deregistered. response=\n%s", format_json_for_log(response))
            return (True, response)
        except Exception as exc:
            self._logger.exception("Failed to deregister robot agent_id=%s.", agent_id)
            return (False, str(exc))

    def join_network(self, agent_id: str) -> tuple[Any, ...]:
        try:
            self._require_local_agent(agent_id)
            if self.network_status == "ONLINE":
                raise RuntimeError("Robot is already online.")

            self.websocket_client = self._create_websocket_client()
            self.moq_pub_client = self._create_moq_client("publisher")
            self.moq_sub_client = self._create_moq_client("subscriber")
            self.task_manager = TaskManager()

            try:
                self.websocket_client.connect()
                self.websocket_client.send_json(
                    self._build_ws_message(
                        "SETUP",
                        {"src_agent_id": agent_id},
                    )
                )
                response = self.websocket_client.receive_json()
                if response.get("type") != "SETUP" or response.get("payload", {}).get("status") != "OK":
                    raise RuntimeError(f"Unexpected setup response: {response}")
                self.moq_pub_client.connect()
                self.moq_sub_client.connect()
            except Exception:
                self.disconnect_all(close_http=False)
                raise

            self.network_status = "ONLINE"
            self._start_network_listener()
            self._logger.info("Network join successful for agent_id=%s", agent_id)
            return (True, agent_id)
        except Exception as exc:
            self._logger.exception("Failed to join network for agent_id=%s.", agent_id)
            return (False, str(exc))

    def logout_network(self, agent_id: str) -> tuple[Any, ...]:
        try:
            self._require_local_agent(agent_id)
            if self.network_status != "ONLINE":
                raise RuntimeError("Robot is not online.")
            if self.websocket_client is not None:
                self.websocket_client.send_json(
                    self._build_ws_message(
                        "DISCONNECTION",
                        {"src_agent_id": agent_id},
                    )
                )
            self.disconnect_all(close_http=False)
            return (True, agent_id)
        except Exception as exc:
            self._logger.exception("Failed to logout network for agent_id=%s.", agent_id)
            return (False, str(exc))

    def request_task_execution(self, agent_id: str, task_info: str, task_id: str | None = None) -> tuple[Any, ...]:
        try:
            self._require_online_agent(agent_id)
            task_id = task_id or self._generate_task_id()
            request = TaskExecutionRequest(
                agent_id=agent_id,
                task_id=task_id,
                description=task_info,
                timestamp=self._utc_timestamp(),
            )
            response = self.http_client.request_task_execution(request)
            task_id = response.get("task_id", task_id)
            self._task_registry[task_id] = {
                "description": task_info,
                "status": "requested",
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
    ) -> tuple[Any, ...]:
        try:
            self._require_online_agent(agent_id)
            request = TaskTerminationRequest(
                agent_id=agent_id,
                task_id=task_id,
                reason=reason,
                timestamp=self._utc_timestamp(),
                force=force,
            )
            response = self.http_client.request_terminate_task(request)
            if task_id in self._task_registry:
                self._task_registry[task_id]["status"] = "terminated"
            self._logger.info("Task termination requested. task_id=%s response=\n%s", task_id, format_json_for_log(response))
            return (True, response)
        except Exception as exc:
            self._logger.exception("Failed to request task termination for task_id=%s.", task_id)
            return (False, str(exc))

    def task_info_report(self, agent_id: str, task_id: str, topic: str, message_info: bytes) -> tuple[Any, ...]:
        try:
            self._require_online_agent(agent_id)
            namespace = f"/{task_id}/{agent_id}"
            track_key = self._track_key(namespace, topic)

            if self.moq_pub_client is None:
                raise RuntimeError("MoQ publisher is not connected. Call join_network() first.")

            if track_key not in self._published_tracks:
                self.moq_pub_client.publish(namespace, topic)
                if self.websocket_client is None:
                    raise RuntimeError("WebSocket is not connected.")
                self.websocket_client.send_json(
                    self._build_ws_message(
                        "PUBLISH_TRACK",
                        {
                            "src_agent_id": agent_id,
                            "task_id": task_id,
                            "track_list": [{"namespace": namespace, "track": topic}],
                        },
                    )
                )
                self._published_tracks.add(track_key)

            self.moq_pub_client.send_object(namespace, topic, message_info)
            self._logger.info(
                "Task info reported. agent_id=%s task_id=%s topic=%s payload_size=%s",
                agent_id,
                task_id,
                topic,
                len(message_info),
            )
            return (True, task_id, topic)
        except Exception as exc:
            self._logger.exception("Failed to report task info for task_id=%s topic=%s.", task_id, topic)
            return (False, str(exc))

    def request_task_collaboration(
        self,
        agent_id: str,
        task_id: str,
        required_capabilities: str | list[str],
    ) -> tuple[Any, ...]:
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
            response = self.http_client.request_task_collaboration(request)
            self._logger.info("Task collaboration requested. task_id=%s response=\n%s", task_id, format_json_for_log(response))
            return (True, response)
        except Exception as exc:
            self._logger.exception("Failed to request task collaboration for task_id=%s.", task_id)
            return (False, str(exc))

    def accept_task_collaboration(
        self,
        agent_id: str,
        task_id: str,
        dst_agent_id: str | None = None,
    ) -> tuple[Any, ...]:
        try:
            self._require_online_agent(agent_id)
            if self.websocket_client is None:
                raise RuntimeError("WebSocket is not connected.")
            if dst_agent_id is None:
                task_context = self._task_registry.get(task_id, {})
                dst_agent_id = task_context.get("requesting_agent_id")
            if not dst_agent_id:
                raise ValueError(f"dst_agent_id must be provided for task_id={task_id}.")
            message = self._build_ws_message(
                "TASK_ACCEPT_COLLABORATION",
                {
                    "src_agent_id": agent_id,
                    "dst_agent_id": dst_agent_id,
                    "task_id": task_id,
                    "result": "OK",
                },
            )
            self.websocket_client.send_json(message)
            self._logger.info("Task collaboration accepted. task_id=%s dst_agent_id=%s", task_id, dst_agent_id)
            return (True, task_id)
        except Exception as exc:
            self._logger.exception("Failed to accept task collaboration for task_id=%s.", task_id)
            return (False, str(exc))

    def start_task(self, agent_id: str, dst_agent_id: str, task_id: str, task_description: str) -> tuple[Any, ...]:
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
            self.websocket_client.send_json(message)
            self._logger.info(
                "Start task message sent. src_agent_id=%s dst_agent_id=%s task_id=%s",
                agent_id,
                dst_agent_id,
                task_id,
            )
            return (True, task_id, dst_agent_id)
        except Exception as exc:
            self._logger.exception("Failed to start task task_id=%s dst_agent_id=%s.", task_id, dst_agent_id)
            return (False, str(exc))

    def handle_network_message(self, message: str | dict[str, Any]) -> tuple[Any, ...]:
        try:
            parsed_message = json.loads(message) if isinstance(message, str) else message
            envelope = WebSocketMessage.model_validate(parsed_message)
            message_type = envelope.type
            payload = envelope.payload
            self._logger.info("Handling network message type=%s payload=\n%s", message_type, format_json_for_log(payload))

            if message_type == "SUBSCRIBE_TRACK":
                self._handle_subscribe_track(payload)
            elif message_type == "CLEAR":
                self._published_tracks.clear()
                self._subscribed_tracks.clear()
                self._task_registry.clear()
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
            elif message_type == "START_TASK":
                self._dispatch_message_callback("on_task_start_command", self.on_task_start_command, payload)

            if self.on_message_received is not None:
                self.on_message_received(message_type, payload)
            return (True, parsed_message)
        except Exception as exc:
            self._logger.exception("Failed to handle network message.")
            return (False, str(exc))

    def connect_network(self) -> tuple[Any, ...]:
        try:
            self.websocket_client = self._create_websocket_client()
            self.moq_pub_client = self._create_moq_client("publisher")
            self.moq_sub_client = self._create_moq_client("subscriber")
            self.task_manager = TaskManager()
            self.network_status = "ONLINE"
            self._logger.info("Network components initialized without handshake. network_status=%s", self.network_status)
            return (True,)
        except Exception as exc:
            self._logger.exception("Failed to initialize network components.")
            return (False, str(exc))

    def disconnect_all(self, close_http: bool = True) -> tuple[Any, ...]:
        try:
            self._stop_network_listener()
            if close_http:
                if self.http_client is not None:
                    self.http_client.close()
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
            self._published_tracks.clear()
            self._subscribed_tracks.clear()
            self.network_status = "OFFLINE"
            self._logger.info("Network state changed to %s", self.network_status)
            return (True,)
        except Exception as exc:
            self._logger.exception("Failed to disconnect network components.")
            return (False, str(exc))

    def _apply_config(self) -> None:
        setup_logging(self.config.log_level, self.config.storage.log_dir)
        self._logger = logging.getLogger(self.__class__.__name__)
        self.identity_manager = IdentityManager(self.config.storage.identity_file)
        self.http_client = HttpClient(self.config.network.acn_agent_url, self.config.network.arf_url)
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
        for track_info in payload.get("track_list", []):
            namespace = track_info["namespace"]
            track = track_info["track"]
            track_key = self._track_key(namespace, track)
            if track_key in self._subscribed_tracks:
                continue
            self.moq_sub_client.subscribe(namespace, track, self.identity_manager.agent_id or self.robot_name)
            self._subscribed_tracks.add(track_key)

    def _handle_moq_object_received(self, namespace: str, track: str, payload: bytes) -> None:
        moq_message = {
            "namespace": namespace,
            "track": track,
            "message_info": payload,
        }
        if self.on_moq_message_received is not None:
            self.on_moq_message_received(namespace, track, payload)
        if self.on_message_received is not None:
            self.on_message_received("MOQ_OBJECT", moq_message)

    def _start_network_listener(self) -> None:
        if self.websocket_client is None:
            raise RuntimeError("WebSocket is not connected.")
        if self._network_listener_thread is not None and self._network_listener_thread.is_alive():
            return
        self._network_listener_stop = threading.Event()
        self._network_listener_thread = threading.Thread(
            target=self._network_listener_loop,
            name=f"AcnSDKNetworkListener-{self.robot_name}",
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
        if self.network_status != "ONLINE":
            raise RuntimeError("Robot must be online before performing task operations.")

    def _build_ws_message(self, message_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return WebSocketMessage(
            type=message_type,
            timestamp=self._utc_timestamp(),
            payload=payload,
        ).model_dump(mode="json")

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
