from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def ensure_ec_keypair(private_key_file: str, public_key_file: str) -> None:
    private_path = Path(private_key_file)
    public_path = Path(public_key_file)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)

    if private_path.exists() and public_path.exists():
        if _is_ec_keypair(private_path, public_path):
            return

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_bytes)
    public_path.write_bytes(public_bytes)


def load_public_key_pem(public_key_file: str) -> str:
    return Path(public_key_file).read_text(encoding="utf-8")


def _is_ec_keypair(private_path: Path, public_path: Path) -> bool:
    try:
        private_key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
        public_key = serialization.load_pem_public_key(public_path.read_bytes())
    except (ValueError, TypeError):
        return False

    return isinstance(private_key, ec.EllipticCurvePrivateKey) and isinstance(
        public_key, ec.EllipticCurvePublicKey
    )


def sign_payload(private_key_file: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    private_key = serialization.load_pem_private_key(
        Path(private_key_file).read_bytes(),
        password=None,
    )
    signature = private_key.sign(
        serialized,
        ec.ECDSA(hashes.SHA256()),
    )
    return base64.b64encode(signature).decode("utf-8")
