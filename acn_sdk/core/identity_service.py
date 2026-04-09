from __future__ import annotations

from typing import Any

from ..utils.crypto import load_public_key_pem, sign_timestamp
from .models import (
    AgentCardRequest,
    AgentInfo,
    AgentInfoQueryRequest,
    DeregisterRequest,
    OwnerAgentsQueryRequest,
)
from .common import NETWORK_ONLINE


class SDKIdentityMixin:
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
            self._logger.info("Agent registered. agent_id=%s", agent_id)
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
            self._logger.info("Robot attribute registered. agent_id=%s", agent_id)
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
                self._logger.info("Queried local agent info agent_id=%s", agent_id)
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
            self._logger.info("Queried remote agent info agent_id=%s", agent_id)
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
            self._logger.info("Queried agent list owner=%s", owner_name)
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
            self._logger.info("Robot deregistered. agent_id=%s", agent_id)
            return (True, self._stringify_result(response))
        except Exception as exc:
            self._logger.exception("Failed to deregister robot agent_id=%s.", agent_id)
            return (False, str(exc))

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
