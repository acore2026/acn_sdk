from __future__ import annotations

import argparse
import logging

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

from acn_sdk.logging_config import setup_logging


setup_logging()
logger = logging.getLogger("mock_arf")
app = FastAPI(title="Mock ARF", version="0.1.0")
AGENT_CARD_REGISTRY: dict[str, dict] = {}


class AgentCard(BaseModel):
    agent_id: str
    priority: int
    timestamp: str
    signature: str
    signature_encoding: str
    vc_list: list[dict]


class AgentDiscovery(BaseModel):
    task_id: str
    agent_id: str
    required_capabilities: list[str]
    timestamp: str


@app.post("/arf/v1/agent-cards")
def create_agent_card(payload: AgentCard) -> dict:
    logger.info("Received agent card registration: %s", payload.model_dump(mode="json"))
    capabilities = [vc["claims"]["agent_attribute"] for vc in payload.vc_list[1:] if "claims" in vc and "agent_attribute" in vc["claims"]]
    vc0_claims = payload.vc_list[0].get("claims", {}) if payload.vc_list else {}
    AGENT_CARD_REGISTRY[payload.agent_id] = {
        "agent_id": payload.agent_id,
        "agent_name": vc0_claims.get("agent_name", ""),
        "agent_status": "online",
        "agent_capabilities": capabilities,
        "priority": payload.priority,
    }
    response = {
        "result": "success",
        "message": "Agent capability registered",
        "agent_id": payload.agent_id,
        "capabilities": capabilities,
    }
    logger.info("Responding agent card registration: %s", response)
    return response


@app.post("/arf/v1/agent-discoveries")
def request_agent_discovery(payload: AgentDiscovery) -> dict:
    logger.info("Received agent discovery request: %s", payload.model_dump(mode="json"))
    response = {
        "result": "success",
        "message": "Agent discovery requested",
        "agent_id": payload.agent_id,
        "task_id": payload.task_id,
        "required_capabilities": payload.required_capabilities,
    }
    logger.info("Responding agent discovery request: %s", response)
    return response


@app.post("/arf/v1/agent-info")
def query_agent_info(payload: dict) -> dict:
    logger.info("Received agent info query: %s", payload)
    agent_id = payload.get("agent_id", "")
    if agent_id not in AGENT_CARD_REGISTRY:
        return {
            "agent_id": agent_id,
            "agent_name": "",
            "agent_status": "offline",
            "agent_capabilities": [],
            "priority": 0,
        }
    response = AGENT_CARD_REGISTRY[agent_id]
    logger.info("Responding agent info query: %s", response)
    return response


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the mock ARF service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9001)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
