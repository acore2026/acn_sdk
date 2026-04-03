# -*- coding: utf-8 -*-
from __future__ import annotations
import sys
sys.path.append('..')
from acn_sdk import AcnSDK, AgentInfo


def main() -> None:
    sdk = AcnSDK(agent_name="AliceAgent")

    agent_info = AgentInfo(
        name="AliceAgent",
        owner="13800138000",
        description="AgentModel-X, SN123456",
        priority=5,
        metadata={"region": "CN", "os": "Linux", "version": "1.0.0"},
    )

    result, agent_id = sdk.register_agent_info(agent_info)
    if not result:
        raise RuntimeError(agent_id)
    print(f"registered agent_id={agent_id}")

    result, capability_response = sdk.register_agent_attribute(agent_id, ["可疑人员识别", "目标跟踪", "声光驱离"])
    if not result:
        raise RuntimeError(capability_response)
    print(f"first capability registration response={capability_response}")

    result, capability_response = sdk.register_agent_attribute(agent_id, ["目标跟踪", "无人机侦测"])
    if not result:
        raise RuntimeError(capability_response)
    print(f"second capability registration response={capability_response}")

    result, query_result = sdk.query_agent_id("AliceAgent", "13800138000")
    print(f"query result={query_result}")

    result, deregister_response = sdk.deregister_agent(agent_id, "retired")
    if not result:
        raise RuntimeError(deregister_response)
    print(f"deregister response={deregister_response}")


if __name__ == "__main__":
    main()
