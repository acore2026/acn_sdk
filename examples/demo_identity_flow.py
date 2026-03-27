from __future__ import annotations

from acn_sdk import AcnSDK, RobotInfo


def main() -> None:
    sdk = AcnSDK(robot_name="AliceAgent")

    robot_info = RobotInfo(
        name="AliceAgent",
        owner="+8613800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={"region": "CN", "os": "Linux", "version": "1.0.0"},
    )

    agent_id = sdk.register_robot_info(robot_info)
    print(f"registered agent_id={agent_id}")

    capability_response = sdk.register_agent_attribute(["pick", "place", "navigate"])
    print(f"capability registration response={capability_response}")

    query_result = sdk.query_robot_id("AliceAgent", "+8613800138000")
    print(f"query result={query_result}")

    deregister_response = sdk.deregister_robot(agent_id, "retired")
    print(f"deregister response={deregister_response}")


if __name__ == "__main__":
    main()
