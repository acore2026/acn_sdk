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
ROBOT_FACTORY_ISSUER_DID = "did:robotfactoryissuer@6gc.mnc015.mcc234.3gppnetwork"
SPECIAL_HUAWEI_CAPABILITIES = {"可疑人员识别", "目标跟踪"}
CERT_DIR = Path(__file__).resolve().parent / "cert"
PRIVATE_KEY_PASSWORD = b"aicore2026"


def sign_data(private_key_path: str, message: bytes) -> bytes:
    with open(private_key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=PRIVATE_KEY_PASSWORD,
        )

    return private_key.sign(message, ec.ECDSA(hashes.SHA256()))


def _resolve_issuer_profile(capability: str) -> tuple[str, Path, str]:
    if capability in SPECIAL_HUAWEI_CAPABILITIES:
        return HUAWEI_ISSUER_DID, CERT_DIR / "Huawei_private_key.pem", "huawei"
    return ROBOT_FACTORY_ISSUER_DID, CERT_DIR / "Robot_Factory_private_key.pem", "robot-factory"


class CredentialIssuer:
    def __init__(self, issuer_id: str = HUAWEI_ISSUER_DID) -> None:
        self.issuer_id = issuer_id
        self._logger = logging.getLogger(self.__class__.__name__)

    def fetch_capacity_vc(self, agent_id: str, capabilities: list[str], agent_name: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        vcs = []
        for capability in capabilities:
            issuer_id, private_key_path, credential_prefix = _resolve_issuer_profile(capability)
            credential_suffix = f"{secrets.randbelow(10000):04d}"
            vc = {
                "context": ["3gpp-ts-33.xxx-v20.0.0"],
                "id": f"{credential_prefix}/credentials/{credential_suffix}",
                "type": ["VerifiableCredential", "BindingSIMCredential"],
                "issuer": issuer_id,
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
                sign_data(str(private_key_path), signature_payload)
            ).decode("utf-8")
            vcs.append(
                {
                    **vc,
                    "proof": {
                        "creator": f"{issuer_id}#keys-1",
                        "signature_value": signature_value,
                    },
                }
            )
        self._logger.info("Issued capability VCs: %s", vcs)
        return vcs
