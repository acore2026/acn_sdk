from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

from acn_sdk.logging_config import setup_logging


setup_logging()
logger = logging.getLogger("mock_acn_agent")
app = FastAPI(title="Mock ACN Agent", version="0.1.0")
ARF_BASE_URL = "http://127.0.0.1:9001"
AGENT_REGISTRY: dict[str, dict] = {}


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
    pass


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


def _forward_to_arf(path: str, payload: dict) -> dict:
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        response = client.post(f"{ARF_BASE_URL}{path}", json=payload)
    result = response.json()
    if response.status_code >= 400:
        raise RuntimeError(f"ARF request failed: {response.status_code}, {result}")
    return result


@app.post("/idm/v1/identity-applications")
def create_identity_application(payload: IdentityApplication) -> dict:
    logger.info("Received identity application: %s", payload.model_dump(mode="json"))
    now = datetime.now(timezone.utc)
    agent_id = f"did:acn:agent:{uuid4()}"
    response = {
        "result": "success",
        "agent_id": agent_id,
        "vc0": {
            "context": ["3gpp-ts-33.xxx-v20.0.0"],
            "id": f"CMCC/credentials/{uuid4()}",
            "type": ["VerifiableCredential", "BindingSIMCredential"],
            "issuer": "did:udid:NewTypeOperator.rid678@6gc.mnc015.mcc234.3gppnetwork",
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(days=365)).isoformat(),
            "claims": {
                "agent_name": payload.name,
                "agent_id": agent_id,
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
    AGENT_REGISTRY[agent_id] = {
        "agent_id": agent_id,
        "agent_name": payload.name,
        "agent_status": "offline",
        "agent_capabilities": [],
        "priority": 0,
        "owner": payload.owner,
    }
    logger.info("Responding identity application: %s", response)
    return response


@app.post("/arf/v1/agent-cards")
def create_agent_card(payload: dict) -> dict:
    logger.info("Forwarding agent card registration to ARF: %s", payload)
    agent_entry = AGENT_REGISTRY.setdefault(
        payload.get("agent_id", ""),
        {
            "agent_id": payload.get("agent_id", ""),
            "agent_name": "",
            "agent_status": "offline",
            "agent_capabilities": [],
            "priority": 0,
            "owner": "",
        },
    )
    capabilities = [
        vc["claims"]["agent_attribute"]
        for vc in payload.get("vc_list", [])[1:]
        if "claims" in vc and "agent_attribute" in vc["claims"]
    ]
    agent_entry["agent_capabilities"] = capabilities
    agent_entry["priority"] = payload.get("priority", 0)
    agent_entry["agent_status"] = "online"
    response = _forward_to_arf("/arf/v1/agent-cards", payload)
    logger.info("Responding forwarded agent card registration: %s", response)
    return response


@app.post("/arf/v1/agent-discoveries")
def request_agent_discovery(payload: dict) -> dict:
    logger.info("Forwarding agent discovery request to ARF: %s", payload)
    response = _forward_to_arf("/arf/v1/agent-discoveries", payload)
    logger.info("Responding forwarded agent discovery request: %s", response)
    return response

@app.post("/acn-agent/v1/agent-deletions")
def delete_agent(payload: AgentDeletion) -> dict:
    logger.info("Received agent deletion: %s", payload.model_dump(mode="json"))
    if payload.agent_id in AGENT_REGISTRY:
        AGENT_REGISTRY[payload.agent_id]["agent_status"] = "offline"
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


@app.post("/acn-agent/v1/owner-agents")
def query_owner_agents(payload: dict) -> list[dict]:
    logger.info("Received owner agent list query: %s", payload)
    owner = payload.get("owner", "")
    response = [
        {
            "agent_id": agent_info["agent_id"],
            "agent_name": agent_info["agent_name"],
            "agent_status": agent_info["agent_status"],
            "agent_capabilities": agent_info["agent_capabilities"],
            "priority": agent_info["priority"],
        }
        for agent_info in AGENT_REGISTRY.values()
        if agent_info.get("owner") == owner
    ]
    logger.info("Responding owner agent list query: %s", response)
    return response


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the mock ACN Agent service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9010)
    parser.add_argument("--arf-host", default="127.0.0.1")
    parser.add_argument("--arf-port", type=int, default=9001)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    global ARF_BASE_URL
    ARF_BASE_URL = f"http://{args.arf_host}:{args.arf_port}"
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
