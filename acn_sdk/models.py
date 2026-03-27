from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RobotInfo(BaseModel):
    name: str
    owner: str = Field(pattern=r"^\+?[0-9]{6,20}$")
    description: str
    priority: int = Field(ge=0, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCardRequest(BaseModel):
    agent_id: str
    priority: int
    timestamp: str
    signature: str
    vc_list: list[dict[str, Any]]
    signature_encoding: str = "base64"


class DeregisterRequest(BaseModel):
    agent_id: str
    reason: str
    timestamp: str
    signature: str
    signature_encoding: str = "base64"
