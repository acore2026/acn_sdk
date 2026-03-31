from __future__ import annotations

import base64
import json
import httpx
import time
from collections import deque
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
from acn_sdk.network.moq_client import MoQClient


class MockWebSocketClient:
    def __init__(self, response_messages: list[dict[str, object]] | None = None) -> None:
        self.url = "ws://127.0.0.1:9002/ws"
        self.connected = False
        self.sent_messages: list[dict[str, object]] = []
        self._responses = deque(response_messages or [])
        self._closed = False

    def connect(self) -> None:
        self.connected = True
        self._closed = False

    def send_json(self, payload: dict[str, object]) -> None:
        self.sent_messages.append(payload)

    def receive_json(self) -> dict[str, object]:
        while True:
            if self._responses:
                return self._responses.popleft()
            if self._closed:
                raise RuntimeError("Mock websocket closed")
            time.sleep(0.01)

    def disconnect(self) -> None:
        self.connected = False
        self._closed = True

    def push_message(self, payload: dict[str, object]) -> None:
        self._responses.append(payload)

class RecordingMoQClient(MoQClient):
    def __init__(self, host: str, remote_port: int, role: str, on_object_received=None) -> None:
        self.host = host
        self.remote_port = remote_port
        self.role = role
        self.on_object_received = on_object_received
        self.connected = False
        self.published: list[tuple[str, str]] = []
        self.sent_objects: list[tuple[str, str, bytes]] = []
        self.subscribed: list[tuple[str, str, str]] = []
        self._published_tracks: set[str] = set()
        self._subscriptions: dict[str, list[str]] = {}

    def connect(self) -> None:
        self.connected = True

    def publish(self, namespace: str, track: str) -> None:
        self.published.append((namespace, track))
        self._published_tracks.add(f"{namespace}::{track}")

    def send_object(self, namespace: str, track: str, payload: bytes) -> None:
        self.sent_objects.append((namespace, track, payload))

    def subscribe(self, namespace: str, track: str, subscriber_id: str) -> None:
        self.subscribed.append((namespace, track, subscriber_id))
        self._subscriptions.setdefault(f"{namespace}::{track}", []).append(subscriber_id)

    def disconnect(self) -> None:
        self.connected = False

    def simulate_incoming_object(self, namespace: str, track: str, payload: bytes) -> None:
        if self.on_object_received is not None:
            self.on_object_received(namespace, track, payload)


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

    result, agent_id = sdk.register_agent_info(robot_info)
    assert result is True
    assert agent_id.startswith("did:acn:agent:")
    assert sdk.identity_manager.vc0 is not None

    result, capability_response = sdk.register_agent_attribute(agent_id, ["pick", "place"])
    assert result is True
    assert capability_response["result"] == "success"
    assert len(sdk.identity_manager.capability_vcs) == 2
    assert sdk.identity_manager.capability_names == ["pick", "place"]
    assert capability_response["capabilities"] == ["pick", "place"]

    result, capability_response = sdk.register_agent_attribute(agent_id, ["place", "move"])
    assert result is True
    assert capability_response["result"] == "success"
    assert len(sdk.identity_manager.capability_vcs) == 3
    assert sdk.identity_manager.capability_names == ["pick", "place", "move"]
    assert capability_response["capabilities"] == ["pick", "place", "move"]

    result, query_result = sdk.query_robot_id("AliceAgent", "+8613800138000")
    assert result is True
    assert query_result == agent_id

    result, deregister_response = sdk.deregister_robot(agent_id, "retired")
    assert result is True
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

    result, agent_id = sdk.register_agent_info(robot_info)
    assert result is True
    identity_request = sdk.http_client._session.requests[0][1]

    result, capability_response = sdk.register_agent_attribute(agent_id, ["pick"])
    assert result is True
    agent_card_request = sdk.http_client._session.requests[1][1]

    result, deregister_response = sdk.deregister_robot(agent_id, "retired")
    assert result is True
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
    result, _ = sdk.register_agent_info(robot_info)
    assert result is True

    result, message = sdk.register_agent_attribute("did:acn:agent:other", ["pick"])
    assert result is False
    assert "does not match this device" in message


def test_deregister_with_mismatched_agent_id_raises(sdk_environment: object) -> None:
    sdk = create_sdk()
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={},
    )
    result, _ = sdk.register_agent_info(robot_info)
    assert result is True

    result, message = sdk.deregister_robot("did:acn:agent:other", "retired")
    assert result is False
    assert "does not match this device" in message


def test_connect_network_uses_new_config_ports(sdk_environment: object) -> None:
    sdk = create_sdk()

    assert sdk.config.network.acn_agent_url == "http://127.0.0.1:9010"

    result = sdk.connect_network()
    assert result == (True,)

    assert sdk.network_status == "ONLINE"
    assert sdk.websocket_client is not None
    assert sdk.websocket_client.url == "ws://127.0.0.1:9002/ws"
    assert sdk.moq_pub_client is not None
    assert sdk.moq_pub_client.host == "127.0.0.1"
    assert sdk.moq_pub_client.remote_port == 9003
    assert sdk.moq_pub_client.role == "publisher"
    assert sdk.moq_sub_client is not None
    assert sdk.moq_sub_client.host == "127.0.0.1"
    assert sdk.moq_sub_client.remote_port == 9003
    assert sdk.moq_sub_client.role == "subscriber"

    assert sdk.disconnect_all() == (True,)
    assert sdk.network_status == "OFFLINE"


def test_join_network_and_task_flow(sdk_environment: object) -> None:
    messages: list[tuple[str, dict[str, object]]] = []
    sdk = AcnSDK(robot_name="AliceAgent", on_message_received=lambda msg_type, payload: messages.append((msg_type, payload)))
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={},
    )
    result, agent_id = sdk.register_agent_info(robot_info)
    assert result is True

    websocket_client = MockWebSocketClient(
        [{"type": "SETUP", "timestamp": "2025-01-01T00:00:00Z", "payload": {"status": "OK"}}]
    )
    moq_clients: dict[str, RecordingMoQClient] = {}
    sdk._create_websocket_client = lambda: websocket_client

    def create_moq_client(role: str) -> RecordingMoQClient:
        client = RecordingMoQClient("127.0.0.1", 9003, role, on_object_received=sdk._handle_moq_object_received if role == "subscriber" else None)
        moq_clients[role] = client
        return client

    sdk._create_moq_client = create_moq_client

    result, joined_agent_id = sdk.join_network(agent_id)
    assert result is True
    assert joined_agent_id == agent_id
    assert sdk.network_status == "ONLINE"
    assert websocket_client.sent_messages[0]["type"] == "SETUP"

    result, task_id = sdk.request_task_execution(agent_id, "可疑人员驱离")
    assert result is True
    assert task_id.startswith("task-")

    result, report_task_id, report_topic = sdk.task_info_report(agent_id, task_id, "Location", b"payload")
    assert result is True
    assert report_task_id == task_id
    assert report_topic == "Location"
    assert moq_clients["publisher"].published == [(f"/{task_id}/{agent_id}", "Location")]
    assert moq_clients["publisher"].sent_objects == [(f"/{task_id}/{agent_id}", "Location", b"payload")]
    assert websocket_client.sent_messages[1]["type"] == "PUBLISH_TRACK"

    result, collaboration_response = sdk.request_task_collaboration(agent_id, task_id, ["speaker", "light"])
    assert result is True
    assert collaboration_response["result"] == "success"

    collaborator_agent_id = "did:acn:agent:peer-1"
    result, accepted_task_id = sdk.accept_task_collaboration(agent_id, task_id, collaborator_agent_id)
    assert result is True
    assert accepted_task_id == task_id
    assert websocket_client.sent_messages[-1]["type"] == "TASK_ACCEPT_COLLABORATION"
    assert websocket_client.sent_messages[-1]["payload"]["dst_agent_id"] == collaborator_agent_id

    result, started_task_id, dst_agent_id = sdk.start_task_collaboration(
        agent_id,
        "did:acn:agent:peer-1",
        task_id,
        "协同声光驱离",
    )
    assert result is True
    assert started_task_id == task_id
    assert dst_agent_id == "did:acn:agent:peer-1"
    assert websocket_client.sent_messages[-1]["type"] == "START_TASK"

    result, termination_response = sdk.request_terminate_task(agent_id, task_id, "completed", force=False)
    assert result is True
    assert termination_response["result"] == "success"

    result, _ = sdk.handle_network_message(
        {
            "type": "SUBSCRIBE_TRACK",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": agent_id,
                "task_id": task_id,
                "track_list": [{"namespace": f"/{task_id}/{agent_id}", "track": "Location"}],
            },
        }
    )
    assert result is True
    assert moq_clients["subscriber"].subscribed == []

    result, _ = sdk.handle_network_message(
        {
            "type": "SUBSCRIBE_TRACK",
            "timestamp": "2025-01-01T00:00:01Z",
            "payload": {
                "src_agent_id": "did:acn:agent:peer-1",
                "task_id": task_id,
                "track_list": [{"namespace": f"/{task_id}/did:acn:agent:peer-1", "track": "Location"}],
            },
        }
    )
    assert result is True
    assert moq_clients["subscriber"].subscribed == [
        (f"/{task_id}/did:acn:agent:peer-1", "Location", agent_id)
    ]

    moq_clients["subscriber"].simulate_incoming_object(f"/{task_id}/{agent_id}", "Location", b"remote-payload")
    assert messages[-1][0] == "MOQ_OBJECT"
    assert messages[-1][1]["track"] == "Location"

    result, logged_out_agent_id = sdk.logout_network(agent_id)
    assert result is True
    assert logged_out_agent_id == agent_id
    assert sdk.network_status == "OFFLINE"
    assert websocket_client.sent_messages[-1]["type"] == "DISCONNECTION"


def test_request_task_execution_requires_online_state(sdk_environment: object) -> None:
    sdk = create_sdk()
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={},
    )
    result, agent_id = sdk.register_agent_info(robot_info)
    assert result is True

    result, message = sdk.request_task_execution(agent_id, "offline task")
    assert result is False
    assert "online" in message


def test_task_info_report_requires_join_network_for_moq_connections(sdk_environment: object) -> None:
    sdk = create_sdk()
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={},
    )
    result, agent_id = sdk.register_agent_info(robot_info)
    assert result is True
    assert sdk.connect_network() == (True,)

    result, message = sdk.task_info_report(agent_id, "task-12345", "Location", b"payload")
    assert result is False
    assert "not connected" in message
    assert sdk.disconnect_all() == (True,)


def test_join_network_starts_background_listener_for_subscribe_track(sdk_environment: object) -> None:
    messages: list[tuple[str, dict[str, object]]] = []
    sdk = AcnSDK(
        robot_name="AliceAgent",
        on_message_received=lambda msg_type, payload: messages.append((msg_type, payload)),
    )
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={},
    )
    result, agent_id = sdk.register_agent_info(robot_info)
    assert result is True

    websocket_client = MockWebSocketClient(
        [{"type": "SETUP", "timestamp": "2025-01-01T00:00:00Z", "payload": {"status": "OK"}}]
    )
    moq_clients: dict[str, RecordingMoQClient] = {}

    def create_moq_client(role: str) -> RecordingMoQClient:
        client = RecordingMoQClient("127.0.0.1", 9003, role, sdk._handle_moq_object_received if role == "subscriber" else None)
        moq_clients[role] = client
        return client

    sdk._create_websocket_client = lambda: websocket_client
    sdk._create_moq_client = create_moq_client

    result, joined_agent_id = sdk.join_network(agent_id)
    assert result is True
    assert joined_agent_id == agent_id
    websocket_client.push_message(
        {
            "type": "SUBSCRIBE_TRACK",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {
                "src_agent_id": agent_id,
                "task_id": "task-12345",
                "track_list": [{"namespace": f"/task-12345/{agent_id}", "track": "Location"}],
            },
        }
    )

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not moq_clients["subscriber"].subscribed:
        time.sleep(0.01)

    assert moq_clients["subscriber"].subscribed == [(f"/task-12345/{agent_id}", "Location", agent_id)]
    assert messages[-1][0] == "SUBSCRIBE_TRACK"

    result, logged_out_agent_id = sdk.logout_network(agent_id)
    assert result is True
    assert logged_out_agent_id == agent_id


def test_register_callbacks_dispatches_websocket_and_moq_messages(sdk_environment: object) -> None:
    ws_messages: list[tuple[str, dict[str, object]]] = []
    moq_messages: list[tuple[str, str, bytes]] = []
    sdk = create_sdk()
    assert sdk.register_callbacks(
        on_task_collaboration_request=lambda payload: ws_messages.append(("TASK_REQUEST_COLLABORATION", payload)),
        on_discover_result_received=lambda payload: ws_messages.append(("DISCOVER_RESULT", payload)),
        on_task_start_command=lambda payload: ws_messages.append(("START_TASK", payload)),
        on_moq_message_received=lambda namespace, track, payload: moq_messages.append((namespace, track, payload)),
    ) == (True,)

    assert sdk.handle_network_message(
        {
            "type": "TASK_REQUEST_COLLABORATION",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {"task_id": "task-1", "src_agent_id": "did:acn:agent:peer-1"},
        }
    )[0] is True
    assert sdk.handle_network_message(
        {
            "type": "DISCOVER_RESULT",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {"discover_result": ["did:acn:agent:peer-1"]},
        }
    )[0] is True
    assert sdk.handle_network_message(
        {
            "type": "START_TASK",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {"task_id": "task-1", "task_description": "demo task"},
        }
    )[0] is True

    sdk._handle_moq_object_received("/task-1/did:acn:agent:alice", "Location", b"payload")

    assert [message_type for message_type, _ in ws_messages] == ["TASK_REQUEST_COLLABORATION", "DISCOVER_RESULT", "START_TASK"]
    assert ws_messages[2][1]["task_description"] == "demo task"
    assert moq_messages == [("/task-1/did:acn:agent:alice", "Location", b"payload")]


def test_deregister_robot_sends_disconnection_when_online(sdk_environment: object) -> None:
    sdk = create_sdk()
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={},
    )
    result, agent_id = sdk.register_agent_info(robot_info)
    assert result is True
    websocket_client = MockWebSocketClient(
        [{"type": "SETUP", "timestamp": "2025-01-01T00:00:00Z", "payload": {"status": "OK"}}]
    )
    sdk._create_websocket_client = lambda: websocket_client
    sdk._create_moq_client = lambda role: RecordingMoQClient("127.0.0.1", 9003, role)

    result, joined_agent_id = sdk.join_network(agent_id)
    assert result is True
    assert joined_agent_id == agent_id
    result, response = sdk.deregister_robot(agent_id, "retired")

    assert result is True
    assert response["result"] == "success"
    assert websocket_client.sent_messages[-1]["type"] == "DISCONNECTION"
    assert sdk.network_status == "OFFLINE"


def test_reload_config_reflects_yaml_changes(sdk_environment: object) -> None:
    config = sdk_environment
    sdk = create_sdk()

    config.network.acn_agent_port = 9110
    config.network.agent_gw_ws_port = 9012
    config.storage.log_dir = str(Path(config.storage.identity_file).parent / "alt-logs")
    config_path = Path(config.storage.identity_file).parent / "config.yaml"
    config.save(config_path)

    assert sdk.reload_config() == (True,)

    assert sdk.config.network.acn_agent_port == 9110
    assert sdk.config.network.agent_gw_ws_port == 9012
    assert sdk.http_client.base_url == "http://127.0.0.1:9110"


def test_http_client_disables_env_proxy_inheritance() -> None:
    client = HttpClient("http://127.0.0.1:9010", "http://127.0.0.1:9001")
    try:
        assert isinstance(client._session, httpx.Client)
        assert client._session._trust_env is False
        assert isinstance(client._arf_session, httpx.Client)
        assert client._arf_session._trust_env is False
    finally:
        client.close()


def test_request_task_collaboration_uses_arf_http_endpoint(sdk_environment: object) -> None:
    sdk = create_sdk()
    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={},
    )
    result, agent_id = sdk.register_agent_info(robot_info)
    assert result is True

    websocket_client = MockWebSocketClient(
        [{"type": "SETUP", "timestamp": "2025-01-01T00:00:00Z", "payload": {"status": "OK"}}]
    )
    sdk._create_websocket_client = lambda: websocket_client
    sdk._create_moq_client = lambda role: RecordingMoQClient("127.0.0.1", 9003, role)

    result, joined_agent_id = sdk.join_network(agent_id)
    assert result is True
    assert joined_agent_id == agent_id

    result, response = sdk.request_task_collaboration(agent_id, "task-12345", ["speaker"])
    assert result is True
    assert response["result"] == "success"
    assert sdk.http_client.base_url == "http://127.0.0.1:9010"
    assert sdk.http_client.arf_base_url == "http://127.0.0.1:9001"
    assert sdk.http_client._arf_session.requests[-1][0] == "/arf/v1/agent-discoveries"
    assert not sdk.http_client._session.requests or all(
        request[0] != "/arf/v1/agent-discoveries" for request in sdk.http_client._session.requests
    )


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
