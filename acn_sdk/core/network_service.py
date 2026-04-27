from __future__ import annotations

import json
import threading
from typing import Any

from ..network.moq_client import MoQClient
from ..network.websocket_client import WebSocketClient
from ..task.task_manager import TaskManager
from ..utils.logging_utils import format_json_for_log
from .common import NETWORK_OFFLINE, NETWORK_ONLINE


class SDKNetworkMixin:
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
                    abstract=f"{self.identity_manager.agent_name} logs out from the network",
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

    def handle_network_message(self, message: str | dict[str, Any]) -> tuple[bool, str]:
        try:
            parsed_message = json.loads(message) if isinstance(message, str) else message
            envelope = self._validate_ws_message(parsed_message)
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
            elif message_type == "TASK_TERMINATION":
                self._dispatch_message_callback("on_terminate_task_received", self.on_terminate_task_received, payload)

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
                abstract=f"{self.identity_manager.agent_name} subscribes MoQ track: {track}",
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

    @staticmethod
    def _validate_ws_message(message: dict[str, Any]) -> Any:
        from .models import WebSocketMessage

        return WebSocketMessage.model_validate(message)
