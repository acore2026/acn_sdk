from __future__ import annotations

from acn_sdk.models import RobotInfo
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

    capability_response = sdk.register_agent_attribute(["pick", "place"])
    assert capability_response["result"] == "success"
    assert sdk.identity_manager.capability_vc is not None

    query_result = sdk.query_robot_id("AliceAgent", "+8613800138000")
    assert query_result == agent_id

    deregister_response = sdk.deregister_robot(agent_id, "retired")
    assert deregister_response["result"] == "success"
    assert sdk.identity_manager.agent_id is None
    assert sdk.network_status == "OFFLINE"


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
