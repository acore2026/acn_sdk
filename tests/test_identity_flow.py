from __future__ import annotations

import base64
import json
import httpx
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives import serialization

from acn_sdk.credential.credential_issuer import (
    CredentialIssuer,
    HUAWEI_ISSUER_DID,
    ROBOT_FACTORY_ISSUER_DID,
)
from acn_sdk.models import RobotInfo
from acn_sdk.crypto import ensure_ec_keypair, sign_payload
from acn_sdk.network.http_client import HttpClient
from acn_sdk.sdk import AcnSDK


def create_sdk() -> AcnSDK:
    return AcnSDK(robot_name="AliceAgent")


def test_register_query_and_deregister_flow(sdk_environment: object) -> None:
    sdk = create_sdk()
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={"region": "CN", "os": "Linux", "version": "1.0.0"},
    )

    agent_id = sdk.register_robot_info(robot_info)
    assert agent_id.startswith("did:acn:agent:")
    assert sdk.identity_manager.vc0 is not None

    capability_response = sdk.register_agent_attribute(agent_id, ["pick", "place"])
    assert capability_response["result"] == "success"
    assert len(sdk.identity_manager.capability_vcs) == 2
    assert sdk.identity_manager.capability_names == ["pick", "place"]
    assert capability_response["capabilities"] == ["pick", "place"]

    capability_response = sdk.register_agent_attribute(agent_id, ["place", "move"])
    assert capability_response["result"] == "success"
    assert len(sdk.identity_manager.capability_vcs) == 3
    assert sdk.identity_manager.capability_names == ["pick", "place", "move"]
    assert capability_response["capabilities"] == ["pick", "place", "move"]

    query_result = sdk.query_robot_id("AliceAgent", "+8613800138000")
    assert query_result == agent_id

    deregister_response = sdk.deregister_robot(agent_id, "retired")
    assert deregister_response["result"] == "success"
    assert sdk.identity_manager.agent_id is None
    assert sdk.network_status == "OFFLINE"


def test_request_signatures_use_timestamp_only_and_agent_card_encoding_order(sdk_environment: object) -> None:
    sdk = create_sdk()
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={"region": "CN"},
    )

    agent_id = sdk.register_robot_info(robot_info)
    identity_request = sdk.http_client._session.requests[0][1]

    capability_response = sdk.register_agent_attribute(agent_id, ["pick"])
    agent_card_request = sdk.http_client._session.requests[1][1]

    deregister_response = sdk.deregister_robot(agent_id, "retired")
    deregister_request = sdk.http_client._session.requests[2][1]

    assert "priority" not in identity_request
    assert identity_request["signature_encoding"] == "base64"
    assert agent_card_request["signature_encoding"] == "base64"
    assert deregister_request["signature_encoding"] == "base64"
    assert list(agent_card_request.keys()).index("signature_encoding") == list(agent_card_request.keys()).index("signature") + 1

    _verify_timestamp_only_signature(identity_request, Path(sdk.config.storage.public_key_file))
    _verify_timestamp_only_signature(agent_card_request, Path(sdk.config.storage.public_key_file))
    _verify_timestamp_only_signature(deregister_request, Path(sdk.config.storage.public_key_file))

    assert capability_response["result"] == "success"
    assert deregister_response["result"] == "success"


def test_register_agent_attribute_with_mismatched_agent_id_raises(sdk_environment: object) -> None:
    sdk = create_sdk()
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={},
    )
    sdk.register_robot_info(robot_info)

    try:
        sdk.register_agent_attribute("did:acn:agent:other", ["pick"])
    except ValueError as exc:
        assert "does not match this device" in str(exc)
    else:
        raise AssertionError("Expected ValueError to be raised")


def test_deregister_with_mismatched_agent_id_raises(sdk_environment: object) -> None:
    sdk = create_sdk()
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={},
    )
    sdk.register_robot_info(robot_info)

    try:
        sdk.deregister_robot("did:acn:agent:other", "retired")
    except ValueError as exc:
        assert "does not match this device" in str(exc)
    else:
        raise AssertionError("Expected ValueError to be raised")


def test_connect_network_uses_new_config_ports(sdk_environment: object) -> None:
    sdk = create_sdk()

    assert sdk.config.network.acn_agent_url == "http://127.0.0.1:9010"

    sdk.connect_network()

    assert sdk.network_status == "ONLINE"
    assert sdk.websocket_client is not None
    assert sdk.websocket_client.url == "ws://127.0.0.1:9002/ws"
    assert sdk.moq_pub_client is not None
    assert sdk.moq_pub_client.host == "127.0.0.1"
    assert sdk.moq_pub_client.remote_port == 9003
    assert sdk.moq_pub_client.local_port == 8003
    assert sdk.moq_pub_client.role == "publisher"
    assert sdk.moq_sub_client is not None
    assert sdk.moq_sub_client.host == "127.0.0.1"
    assert sdk.moq_sub_client.remote_port == 9003
    assert sdk.moq_sub_client.local_port == 8004
    assert sdk.moq_sub_client.role == "subscriber"

    sdk.disconnect_all()
    assert sdk.network_status == "OFFLINE"


def test_reload_config_reflects_yaml_changes(sdk_environment: object) -> None:
    config = sdk_environment
    sdk = create_sdk()

    config.network.acn_agent_port = 9110
    config.network.agent_gw_ws_port = 9012
    config.storage.log_dir = str(Path(config.storage.identity_file).parent / "alt-logs")
    config_path = Path(config.storage.identity_file).parent / "config.yaml"
    config.save(config_path)

    sdk.reload_config()

    assert sdk.config.network.acn_agent_port == 9110
    assert sdk.config.network.agent_gw_ws_port == 9012
    assert sdk.http_client.base_url == "http://127.0.0.1:9110"


def test_http_client_disables_env_proxy_inheritance() -> None:
    client = HttpClient("http://127.0.0.1:9010")
    try:
        assert isinstance(client._session, httpx.Client)
        assert client._session._trust_env is False
    finally:
        client.close()


def test_ensure_ec_keypair_creates_and_preserves_local_keys(tmp_path: Path) -> None:
    private_key_file = tmp_path / "keys" / "private.pem"
    public_key_file = tmp_path / "keys" / "public.pem"

    ensure_ec_keypair(str(private_key_file), str(public_key_file))
    first_private = private_key_file.read_text(encoding="utf-8")
    first_public = public_key_file.read_text(encoding="utf-8")

    assert "BEGIN PRIVATE KEY" in first_private
    assert "BEGIN PUBLIC KEY" in first_public

    ensure_ec_keypair(str(private_key_file), str(public_key_file))

    assert private_key_file.read_text(encoding="utf-8") == first_private
    assert public_key_file.read_text(encoding="utf-8") == first_public


def test_ensure_ec_keypair_replaces_legacy_rsa_keys(tmp_path: Path) -> None:
    private_key_file = tmp_path / "keys" / "private.pem"
    public_key_file = tmp_path / "keys" / "public.pem"
    private_key_file.parent.mkdir(parents=True, exist_ok=True)

    rsa_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_file.write_bytes(
        rsa_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_key_file.write_bytes(
        rsa_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    ensure_ec_keypair(str(private_key_file), str(public_key_file))

    loaded_private_key = serialization.load_pem_private_key(private_key_file.read_bytes(), password=None)
    loaded_public_key = serialization.load_pem_public_key(public_key_file.read_bytes())
    assert isinstance(loaded_private_key, ec.EllipticCurvePrivateKey)
    assert isinstance(loaded_public_key, ec.EllipticCurvePublicKey)

    signature = sign_payload(str(private_key_file), {"message": "hello"})
    assert isinstance(signature, str)
    assert signature


def test_identity_manager_loads_legacy_single_capability_vc(tmp_path: Path) -> None:
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(
        '{"agent_id":"a1","vc0":{"id":"vc0"},"capability_vc":{"id":"cap1"},"robot_name":"AliceAgent","owner":"+8613800138000","priority":5,"metadata":{}}',
        encoding="utf-8",
    )

    from acn_sdk.identity.identity_manager import IdentityManager

    manager = IdentityManager(str(identity_file))
    assert manager.capability_names == []
    assert manager.capability_vcs == [{"id": "cap1"}]


def test_identity_manager_extracts_capability_names_from_existing_vcs(tmp_path: Path) -> None:
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(
        '{"agent_id":"a1","vc0":{"id":"vc0"},"capability_vcs":[{"id":"cap1","claims":{"agent_attribute":"pick"}},{"id":"cap2","claims":{"agent_attribute":"place"}}],"robot_name":"AliceAgent","owner":"+8613800138000","priority":5,"metadata":{}}',
        encoding="utf-8",
    )

    from acn_sdk.identity.identity_manager import IdentityManager

    manager = IdentityManager(str(identity_file))
    assert manager.capability_names == ["pick", "place"]
    assert manager.get_pending_capabilities(["pick", "move"]) == ["move"]


def test_identity_manager_get_pending_capabilities_deduplicates_input(tmp_path: Path) -> None:
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(
        '{"agent_id":"a1","vc0":{"id":"vc0"},"capability_names":["pick"],"robot_name":"AliceAgent","owner":"+8613800138000","priority":5,"metadata":{}}',
        encoding="utf-8",
    )

    from acn_sdk.identity.identity_manager import IdentityManager

    manager = IdentityManager(str(identity_file))
    assert manager.get_pending_capabilities(["pick", "move", "move", "scan", "scan"]) == ["move", "scan"]


def test_fetch_capacity_vc_uses_issuer_specific_private_key() -> None:
    agent_id = "did:acn:agent:987654321"
    huawei_issuer = CredentialIssuer()
    huawei_vc = huawei_issuer.fetch_capacity_vc(agent_id, ["可疑人员识别"], "AliceAgent")[0]
    assert huawei_vc["id"].startswith("huawei/credentials/")
    assert len(huawei_vc["id"].rsplit("/", 1)[-1]) == 4

    assert huawei_vc["type"] == ["VerifiableCredential", "BindingSIMCredential"]
    assert huawei_vc["issuer"] == HUAWEI_ISSUER_DID
    assert huawei_vc["proof"]["creator"] == f"{HUAWEI_ISSUER_DID}#keys-1"
    _verify_signature(
        huawei_vc,
        Path("/home/acn/zxy/acn_sdk/credential/cert/Huawei_cert.crt"),
    )

    robot_factory_issuer = CredentialIssuer()
    robot_factory_vc = robot_factory_issuer.fetch_capacity_vc(agent_id, ["place"], "AliceAgent")[0]

    assert robot_factory_vc["type"] == ["VerifiableCredential", "BindingSIMCredential"]
    assert robot_factory_vc["issuer"] == ROBOT_FACTORY_ISSUER_DID
    assert robot_factory_vc["proof"]["creator"] == f"{ROBOT_FACTORY_ISSUER_DID}#keys-1"
    _verify_signature(
        robot_factory_vc,
        Path("/home/acn/zxy/acn_sdk/credential/cert/Robot_Factory_cert.crt"),
    )

    mixed_vcs = huawei_issuer.fetch_capacity_vc(agent_id, ["可疑人员识别", "place", "目标跟踪"], "AliceAgent")
    assert [vc["issuer"] for vc in mixed_vcs] == [
        HUAWEI_ISSUER_DID,
        ROBOT_FACTORY_ISSUER_DID,
        HUAWEI_ISSUER_DID,
    ]


def _verify_signature(vc: dict[str, object], cert_path: Path) -> None:
    proof = vc["proof"]
    payload = {key: value for key, value in vc.items() if key != "proof"}
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    cert.public_key().verify(
        base64.b64decode(proof["signature_value"]),
        serialized,
        ec.ECDSA(hashes.SHA256()),
    )


def _verify_timestamp_only_signature(body: dict[str, object], public_key_path: Path) -> None:
    serialized = str(body["timestamp"]).encode("utf-8")
    public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
    public_key.verify(
        base64.b64decode(body["signature"]),
        serialized,
        ec.ECDSA(hashes.SHA256()),
    )
