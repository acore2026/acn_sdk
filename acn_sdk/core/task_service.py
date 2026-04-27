from __future__ import annotations

from typing import Any

from .models import AgentDiscoveryRequest, TaskExecutionRequest, TaskTerminationBroadcastRequest, TaskTerminationRequest
from .common import TASK_PROCESSING, TASK_TERMINATED


class SDKTaskMixin:
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
                abstract=f"{self.identity_manager.agent_name} requests task execution, task id = {task_id}",
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
            self._logger.info("Task execution requested. task_id=%s", task_id)
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
                abstract=f"{self.identity_manager.agent_name} requests task termination, task id = {task_id}",
                content=request.model_dump(mode="json"),
                task_id=task_id,
            )
            response = self.http_client.request_terminate_task(request)
            self._stop_task_tracks(task_id)
            if task_id in self._task_registry:
                self._task_registry[task_id]["status"] = TASK_TERMINATED
            self._logger.info("Task termination requested. task_id=%s", task_id)
            return (True, self._stringify_result(response))
        except Exception as exc:
            self._logger.exception("Failed to request task termination for task_id=%s.", task_id)
            return (False, str(exc))

    def broadcast_terminate_task(
        self,
        agent_id: str,
        task_id: str,
        reason: str = "",
        force: bool = False,
    ) -> tuple[bool, str]:
        try:
            self._require_online_agent(agent_id)
            request = TaskTerminationBroadcastRequest(
                agent_id=agent_id,
                task_id=task_id,
                reason=reason,
                timestamp=self._utc_timestamp(),
                force=str(force).lower(),
            )
            self._report_pipeline_log(
                protocol="HTTP",
                destination="ACN Agent",
                method="POST",
                url="/acn-agent/v1/task-termination-broadcasts",
                headers={"Content-Type": "application/json"},
                abstract=f"{self.identity_manager.agent_name} broadcasts task termination, task id = {task_id}",
                content=request.model_dump(mode="json"),
                task_id=task_id,
            )
            result, message = self.http_client.broadcast_terminate_task(request)
            if not result:
                raise RuntimeError(message)
            self._logger.info("Task termination broadcast sent. task_id=%s", task_id)
            return (True, "")
        except Exception as exc:
            self._logger.exception("Failed to broadcast task termination for task_id=%s.", task_id)
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
                    abstract=f"{self.identity_manager.agent_name} publishes MoQ track: {topic}",
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
                    abstract=f"{self.identity_manager.agent_name} announces MoQ published track: {topic}",
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
                abstract=(
                    f"{self.identity_manager.agent_name} requests task collaboration "
                    f"with required capabilities: {', '.join(capability_list)}"
                ),
                content=request.model_dump(mode="json"),
                task_id=task_id,
            )
            response = self.http_client.request_task_collaboration(request)
            self._logger.info("Task collaboration requested. task_id=%s", task_id)
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
                abstract=f"{self.identity_manager.agent_name} accepts task collaboration",
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
                abstract=f"{self.identity_manager.agent_name} notifies the collaborator to start task collaboration",
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
