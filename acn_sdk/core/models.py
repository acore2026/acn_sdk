from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentInfo(BaseModel):
    name: str
    owner: str = Field(pattern=r"^\+?[0-9]{6,20}$")
    description: str
    priority: int = Field(default=1, ge=0, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCardRequest(BaseModel):
    agent_id: str
    priority: int
    timestamp: str
    signature: str
    signature_encoding: str = "base64"
    vc_list: list[dict[str, Any]]


class DeregisterRequest(BaseModel):
    agent_id: str
    reason: str
    timestamp: str
    signature: str
    signature_encoding: str = "base64"


class TaskExecutionRequest(BaseModel):
    agent_id: str
    task_id: str
    description: str
    timestamp: str


class TaskTerminationRequest(BaseModel):
    agent_id: str
    task_id: str
    reason: str
    timestamp: str
    force: bool = False


class TaskTerminationBroadcastRequest(BaseModel):
    agent_id: str
    task_id: str
    reason: str
    timestamp: str
    force: str = "false"


class AgentDiscoveryRequest(BaseModel):
    task_id: str
    agent_id: str
    required_capabilities: list[str]
    timestamp: str


class AgentInfoQueryRequest(BaseModel):
    agent_id: str


class OwnerAgentsQueryRequest(BaseModel):
    owner: str


class WebSocketMessage(BaseModel):
    type: str
    timestamp: str
    payload: dict[str, Any]
