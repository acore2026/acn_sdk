from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


class CredentialIssuer:
    def __init__(self, issuer_id: str = "did:third-party:capability-issuer") -> None:
        self.issuer_id = issuer_id
        self._logger = logging.getLogger(self.__class__.__name__)

    def fetch_capacity_vc(self, agent_id: str, capabilities: list[str]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        vc = {
            "context": ["https://www.w3.org/2018/credentials/v1"],
            "id": f"{self.issuer_id}/credentials/{uuid4()}",
            "type": ["VerifiableCredential", "CapabilityCredential"],
            "issuer": self.issuer_id,
            "valid_from": now.isoformat(),
            "valid_until": (now + timedelta(days=365)).isoformat(),
            "claims": {
                "agent_id": agent_id,
                "capabilities": capabilities,
                "scope": "robot-service-capability",
            },
            "proof": {
                "creator": f"{self.issuer_id}#keys-1",
                "signature_value": f"mock-signature-{uuid4()}",
            },
        }
        self._logger.info("Issued capability VC: %s", vc)
        return vc
