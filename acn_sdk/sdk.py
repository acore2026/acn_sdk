from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import SDKConfig
from .credential.credential_issuer import CredentialIssuer
from .crypto import ensure_rsa_keypair, load_public_key_pem, sign_payload
from .identity.identity_manager import IdentityManager
from .logging_config import setup_logging
from .models import AgentCardRequest, DeregisterRequest, RobotInfo
from .network.http_client import HttpClient
from .network.moq_client import MoQClient
from .network.websocket_client import WebSocketClient
from .task.task_manager import TaskManager

DEFAULT_CONFIG_PATH = Path("config/config.yaml")


class AcnSDK:
    def __init__(self, robot_name: str) -> None:
        self.config = SDKConfig.load(DEFAULT_CONFIG_PATH)
        setup_logging(self.config.log_level, self.config.storage.log_dir)
        self._logger = logging.getLogger(self.__class__.__name__)
        self.robot_name = robot_name
        self.identity_manager = IdentityManager(self.config.storage.identity_file)
        self.http_client = HttpClient(self.config.network.acn_agent_url)
        self.credential_issuer = CredentialIssuer()
        self.websocket_client: WebSocketClient | None = None
        self.moq_pub_client: MoQClient | None = None
        self.moq_sub_client: MoQClient | None = None
        self.task_manager: TaskManager | None = None
        self.network_status = "OFFLINE"

        ensure_rsa_keypair(
            self.config.storage.private_key_file,
            self.config.storage.public_key_file,
        )
        self._logger.info("AcnSDK initialized for robot=%s, network_status=%s", robot_name, self.network_status)
        self._logger.info(
            "SDK local ports http=%s ws=%s moq_pub=%s moq_sub=%s, network acn_agent=%s ws=%s moq=%s web_ui=%s",
            self.config.sdk.http_port,
            self.config.sdk.ws_port,
            self.config.sdk.moq_pub_port,
            self.config.sdk.moq_sub_port,
            self.config.network.acn_agent_port,
            self.config.network.agent_gw_ws_port,
            self.config.network.agent_gw_moq_port,
            self.config.network.web_ui_port,
        )

    def register_robot_info(self, robot_info: RobotInfo) -> str:
        timestamp = self._utc_timestamp()
        payload = {
            "owner": robot_info.owner,
            "name": robot_info.name,
            "public_key": load_public_key_pem(self.config.storage.public_key_file),
            "description": robot_info.description,
            "priority": robot_info.priority,
            "timestamp": timestamp,
            "metadata": robot_info.metadata,
        }
        payload["signature"] = sign_payload(self.config.storage.private_key_file, payload)
        payload["signature_encoding"] = "base64"

        response = self.http_client.register_robot_info(payload)
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
        self._logger.info("Robot registered. agent_id=%s response=%s", agent_id, response)
        return agent_id

    def register_agent_attribute(self, capability: list[str]) -> dict[str, Any]:
        if not self.identity_manager.agent_id or not self.identity_manager.vc0:
            raise RuntimeError("Robot identity must be registered before capabilities.")

        capability_vc = self.credential_issuer.fetch_capacity_vc(
            self.identity_manager.agent_id,
            capability,
        )
        self.identity_manager.set_capability_vc(capability_vc)

        timestamp = self._utc_timestamp()
        sign_source = {
            "agent_id": self.identity_manager.agent_id,
            "capabilities": capability,
            "timestamp": timestamp,
        }
        payload = AgentCardRequest(
            agent_id=self.identity_manager.agent_id,
            robot_name=self.identity_manager.robot_name or self.robot_name,
            owner=self.identity_manager.owner or "",
            priority=self.identity_manager.priority or 0,
            capabilities=capability,
            vc0=self.identity_manager.vc0,
            capability_vc=capability_vc,
            metadata=self.identity_manager.metadata,
            timestamp=timestamp,
            signature=sign_payload(self.config.storage.private_key_file, sign_source),
        )
        response = self.http_client.register_agent_attribute(payload)
        self._logger.info("Robot attribute registered. response=%s", response)
        return response

    def query_robot_id(self, robot_name: str, owner: str) -> str | None:
        agent_id = self.identity_manager.query_robot_id(robot_name, owner)
        self._logger.info(
            "Queried robot identity robot_name=%s owner=%s result=%s",
            robot_name,
            owner,
            agent_id,
        )
        return agent_id

    def deregister_robot(self, agent_id: str, reason: str) -> dict[str, Any]:
        if self.identity_manager.agent_id != agent_id:
            raise ValueError("The supplied agent_id does not match this device.")

        timestamp = self._utc_timestamp()
        sign_source = {
            "agent_id": agent_id,
            "reason": reason,
            "timestamp": timestamp,
        }
        request = DeregisterRequest(
            agent_id=agent_id,
            reason=reason,
            timestamp=timestamp,
            signature=sign_payload(self.config.storage.private_key_file, sign_source),
        )
        response = self.http_client.deregister_robot(request)

        self.identity_manager.clear()
        self.disconnect_all()
        self._logger.info("Robot deregistered. response=%s", response)
        return response

    def connect_network(self) -> None:
        self.websocket_client = WebSocketClient(self.config.network.agent_gw_ws_url)
        self.moq_pub_client = MoQClient(
            host=self.config.network.network_ip,
            remote_port=self.config.network.agent_gw_moq_port,
            local_port=self.config.sdk.moq_pub_port,
            role="publisher",
        )
        self.moq_sub_client = MoQClient(
            host=self.config.network.network_ip,
            remote_port=self.config.network.agent_gw_moq_port,
            local_port=self.config.sdk.moq_sub_port,
            role="subscriber",
        )
        self.task_manager = TaskManager()
        self.moq_pub_client.connect()
        self.moq_sub_client.connect()
        self.network_status = "ONLINE"
        self._logger.info("Network state changed to %s", self.network_status)

    def disconnect_all(self) -> None:
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
        self.network_status = "OFFLINE"
        self._logger.info("Network state changed to %s", self.network_status)

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
