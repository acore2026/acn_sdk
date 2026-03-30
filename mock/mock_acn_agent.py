from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

from acn_sdk.logging_config import setup_logging


setup_logging()
logger = logging.getLogger("mock_acn_agent")
app = FastAPI(title="Mock ACN Agent", version="0.1.0")


class IdentityApplication(BaseModel):
    owner: str
    name: str
    public_key: str
    description: str
    timestamp: str
    signature: str
    signature_encoding: str
    metadata: dict


class AgentCard(BaseModel):
    agent_id: str
    priority: int
    timestamp: str
    signature: str
    signature_encoding: str
    vc_list: list[dict]


class AgentDeletion(BaseModel):
    agent_id: str
    reason: str
    timestamp: str
    signature: str
    signature_encoding: str


class TaskExecution(BaseModel):
    agent_id: str
    task_id: str
    description: str
    timestamp: str


class TaskTermination(BaseModel):
    agent_id: str
    task_id: str
    reason: str
    timestamp: str
    force: bool = False


class AgentDiscovery(BaseModel):
    task_id: str
    agent_id: str
    required_capabilities: list[str]
    timestamp: str


@app.post("/idm/v1/identity-applications")
def create_identity_application(payload: IdentityApplication) -> dict:
    logger.info("Received identity application: %s", payload.model_dump(mode="json"))
    now = datetime.now(timezone.utc)
    response = {
        "result": "success",
        "agent_id": f"did:acn:agent:{uuid4()}",
        "vc0": {
            "context": ["3gpp-ts-33.xxx-v20.0.0"],
            "id": f"CMCC/credentials/{uuid4()}",
            "type": ["VerifiableCredential", "BindingSIMCredential"],
            "issuer": "did:udid:NewTypeOperator.rid678@6gc.mnc015.mcc234.3gppnetwork",
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(days=365)).isoformat(),
            "claims": {
                "agent_name": payload.name,
                "agent_id": f"did:acn:agent:{uuid4()}",
                "agent_attribute": "运营商颁发，Agent与主UE的绑定关系，用于对外出示，审计确权",
                "master_id": "type0.master.mock@3gppnetwork.org",
                "self_id": "type0.self.mock@3gppnetwork.org",
            },
            "proof": {
                "creator": "did:udid:NewTypeOperator.rid678@6gc.mnc015.mcc234.3gppnetwork#keys-1",
                "signature_value": "mock-proof-signature",
            },
        },
    }
    logger.info("Responding identity application: %s", response)
    return response


@app.post("/arf/v1/agent-cards")
def create_agent_card(payload: AgentCard) -> dict:
    logger.info("Received agent card registration: %s", payload.model_dump(mode="json"))
    capabilities = [vc["claims"]["agent_attribute"] for vc in payload.vc_list[1:] if "claims" in vc and "agent_attribute" in vc["claims"]]
    response = {
        "result": "success",
        "message": "Agent capability registered",
        "agent_id": payload.agent_id,
        "capabilities": capabilities,
    }
    logger.info("Responding agent card registration: %s", response)
    return response


@app.post("/acn-agent/v1/agent-deletions")
def delete_agent(payload: AgentDeletion) -> dict:
    logger.info("Received agent deletion: %s", payload.model_dump(mode="json"))
    response = {
        "result": "success",
        "message": "Agent deleted",
        "agent_id": payload.agent_id,
        "reason": payload.reason,
    }
    logger.info("Responding agent deletion: %s", response)
    return response


@app.post("/acn-agent/v1/task-executions")
def request_task_execution(payload: TaskExecution) -> dict:
    logger.info("Received task execution request: %s", payload.model_dump(mode="json"))
    response = {
        "result": "success",
        "message": "Task execution requested",
        "agent_id": payload.agent_id,
        "task_id": payload.task_id,
        "description": payload.description,
    }
    logger.info("Responding task execution request: %s", response)
    return response


@app.post("/acn-agent/v1/task-execution-terminations")
def terminate_task_execution(payload: TaskTermination) -> dict:
    logger.info("Received task termination request: %s", payload.model_dump(mode="json"))
    response = {
        "result": "success",
        "message": "Task termination requested",
        "agent_id": payload.agent_id,
        "task_id": payload.task_id,
        "reason": payload.reason,
        "force": payload.force,
    }
    logger.info("Responding task termination request: %s", response)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the mock ACN Agent service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9010)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
