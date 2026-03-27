from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel

from acn_sdk.logging_config import setup_logging


setup_logging()
logger = logging.getLogger("mock_acn_agent")
app = FastAPI(title="Mock ACN Agent", version="0.1.0")


class IdentityApplication(BaseModel):
    owner: str
    name: str
    public_key: str
    description: str
    priority: int
    timestamp: str
    signature: str
    signature_encoding: str
    metadata: dict


class AgentCard(BaseModel):
    agent_id: str
    priority: int
    timestamp: str
    signature: str
    vc_list: list[dict]
    signature_encoding: str


class AgentDeletion(BaseModel):
    agent_id: str
    reason: str
    timestamp: str
    signature: str
    signature_encoding: str


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
