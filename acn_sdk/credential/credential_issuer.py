from __future__ import annotations

import base64
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


HUAWEI_ISSUER_DID = "did:huaweiissuer@6gc.mnc015.mcc234.3gppnetwork"
CERT_DIR = Path(__file__).resolve().parent / "cert"
PRIVATE_KEY_PASSWORD = b"aicore2026"


def sign_data(private_key_path: str, message: bytes) -> bytes:
    with open(private_key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=PRIVATE_KEY_PASSWORD,
        )

    return private_key.sign(message, ec.ECDSA(hashes.SHA256()))


def _load_private_key_path(issuer_id: str) -> Path:
    issuer_name = issuer_id.lower()
    if "huawei" in issuer_name:
        return CERT_DIR / "Huawei_private_key.pem"
    if "robotfactory" in issuer_name or "robot_factory" in issuer_name or "factory" in issuer_name:
        return CERT_DIR / "Robot_Factory_private_key.pem"
    raise ValueError(f"Unsupported issuer_id for capability VC signing: {issuer_id}")


class CredentialIssuer:
    def __init__(self, issuer_id: str = HUAWEI_ISSUER_DID) -> None:
        self.issuer_id = issuer_id
        self._logger = logging.getLogger(self.__class__.__name__)

    def fetch_capacity_vc(self, agent_id: str, capabilities: list[str], agent_name: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        issuer_name = self.issuer_id.lower()
        credential_prefix = "huawei"
        if "robotfactory" in issuer_name or "robot_factory" in issuer_name or "factory" in issuer_name:
            credential_prefix = "robot_factory"
        vcs = []
        for capability in capabilities:
            credential_suffix = f"{secrets.randbelow(10000):04d}"
            vc = {
                "context": ["3gpp-ts-33.xxx-v20.0.0"],
                "id": f"{credential_prefix}/credentials/{credential_suffix}",
                "type": ["VerifiableCredential", "BindingSIMCredential"],
                "issuer": self.issuer_id,
                "valid_from": now.isoformat(),
                "valid_until": (now + timedelta(days=365)).isoformat(),
                "claims": {
                    "agent_name": agent_name,
                    "agent_id": agent_id,
                    "agent_attribute": capability,
                    "authorization_mode": "Mode2",
                },
            }
            signature_payload = json.dumps(vc, sort_keys=True, separators=(",", ":")).encode("utf-8")
            signature_value = base64.b64encode(
                sign_data(str(_load_private_key_path(self.issuer_id)), signature_payload)
            ).decode("utf-8")
            vcs.append(
                {
                    **vc,
                    "proof": {
                        "creator": f"{self.issuer_id}#keys-1",
                        "signature_value": signature_value,
                    },
                }
            )
        self._logger.info("Issued capability VCs: %s", vcs)
        return vcs
