from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from .core.identity_service import SDKIdentityMixin
from .core.network_service import SDKNetworkMixin
from .core.task_service import SDKTaskMixin
from .core.common import (
    DEFAULT_CONFIG_PATH,
    NETWORK_OFFLINE,
    NETWORK_ONLINE,
    SDKUtilsMixin,
    TASK_PROCESSING,
    TASK_TERMINATED,
)
from .credential.credential_issuer import CredentialIssuer
from .identity.identity_manager import IdentityManager
from .network.http_client import HttpClient
from .network.moq_client import MoQClient
from .network.websocket_client import WebSocketClient
from .reporting.pipeline_log_reporter import PipelineLogReporter
from .task.task_manager import TaskManager
from .utils.crypto import ensure_ec_keypair
from .utils.logging_config import setup_logging


class AcnSDK(SDKIdentityMixin, SDKNetworkMixin, SDKTaskMixin, SDKUtilsMixin):
    def __init__(
        self,
        agent_name: str,
        config_path: str | Path | None = None,
    ) -> None:
        self.config_path = Path(config_path).expanduser().resolve() if config_path is not None else DEFAULT_CONFIG_PATH
        from .core.settings import SDKConfig

        self.config = SDKConfig.load(self.config_path)
        self.agent_name = agent_name
        self.on_task_collaboration_request = None
        self.on_discover_result_received = None
        self.on_task_start_command = None
        self.on_terminate_task_received = None
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

        self._apply_config(reset_identity_cache=True)
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
        on_terminate_task_received: Any | None = None,
        on_message_received: Any | None = None,
    ) -> tuple[bool, str]:
        try:
            if on_task_collaboration_request is not None:
                self.on_task_collaboration_request = on_task_collaboration_request
            if on_discover_result_received is not None:
                self.on_discover_result_received = on_discover_result_received
            if on_task_start_command is not None:
                self.on_task_start_command = on_task_start_command
            if on_terminate_task_received is not None:
                self.on_terminate_task_received = on_terminate_task_received
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

            from .core.settings import SDKConfig

            self.config = SDKConfig.load(self.config_path)
            self._apply_config()
            self._logger.info("Reloaded configuration from %s", self.config_path)
            return (True, "OK")
        except Exception as exc:
            self._logger.exception("Failed to reload configuration from %s.", self.config_path)
            return (False, str(exc))

    def _apply_config(self, *, reset_identity_cache: bool = False) -> None:
        setup_logging(self.config.log_level, self.config.storage.log_dir)
        self._logger = logging.getLogger(self.__class__.__name__)
        if reset_identity_cache:
            identity_file = Path(self.config.storage.identity_file)
            if identity_file.exists():
                identity_file.unlink()
                self._logger.info("Cleared identity cache file: %s", identity_file)
        self.identity_manager = IdentityManager(self.config.storage.identity_file)
        self.http_client = HttpClient(self.config.network.acn_agent_url, self.config.network.arf_url)
        self.pipeline_log_reporter = PipelineLogReporter(self.config.network.web_ui_url)
        ensure_ec_keypair(
            self.config.storage.private_key_file,
            self.config.storage.public_key_file,
        )


__all__ = [
    "AcnSDK",
    "DEFAULT_CONFIG_PATH",
    "NETWORK_OFFLINE",
    "NETWORK_ONLINE",
    "TASK_PROCESSING",
    "TASK_TERMINATED",
]
