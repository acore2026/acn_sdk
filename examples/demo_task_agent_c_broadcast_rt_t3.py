from __future__ import annotations

import time

from acn_sdk import AcnSDK, AgentInfo

DEFAULT_WAIT_TIMEOUT_SECONDS = 150.0


def main() -> None:
    # 1. 初始化 C：参加 B 发起的协作请求
    agent_c = AcnSDK(
        agent_name="SpeakerDroneT3C"
    )

    # 2. 申请 C 的数字身份
    agent_c_ok, agent_c_id = agent_c.register_agent_info(
        AgentInfo(
            name="SpeakerDroneT3C",
            owner="13800138222",
            description="SpeakerDroneModel, SN777777, C joins B",
            priority=4,
            metadata={"region": "CN", "role": "leaf_collaborator", "demo": "t3"},
        )
    )
    if not agent_c_ok:
        raise RuntimeError(agent_c_id)
    print(f"agent_c_id={agent_c_id}")
    print(f"agent_c local agent_info={agent_c.query_agent_info(agent_c_id)}")
    print(f"agent_c owner agents={agent_c.query_agent_list('13800138222')}")

    task_id_holder: dict[str, str] = {"value": ""}

    # 3. 注册回调
    def agent_c_on_task_collaboration_request(payload: dict) -> None:
        print(f"[SpeakerDroneT3C] on_task_collaboration_request payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        print(agent_c.accept_task_collaboration(agent_c_id, task_id))

    def agent_c_on_discover_result_received(payload: dict) -> None:
        print(f"[SpeakerDroneT3C] on_discover_result_received payload={payload}")

    def agent_c_on_task_start_command(payload: dict) -> None:
        print(f"[SpeakerDroneT3C] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        print(
            agent_c.request_task_execution(
                agent_c_id,
                payload["task_description"],
                task_id=task_id,
            )
        )

    def agent_c_on_terminate_task_received(payload: dict) -> None:
        print(f"[SpeakerDroneT3C] on_terminate_task_received payload={payload}")
        task_id = payload.get("task_id")
        reason = payload.get("reason", "")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("task_id is not available in TASK_TERMINATION payload")
        result = agent_c.request_terminate_task(agent_c_id, task_id, reason)
        print(f"[SpeakerDroneT3C] request_terminate_task result={result}")

    def agent_c_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    agent_c.register_callbacks(
        on_task_collaboration_request=agent_c_on_task_collaboration_request,
        on_discover_result_received=agent_c_on_discover_result_received,
        on_task_start_command=agent_c_on_task_start_command,
        on_terminate_task_received=agent_c_on_terminate_task_received,
        on_message_received=agent_c_on_message_received,
    )

    # 4. 能力注册
    print(agent_c.register_agent_attribute(agent_c_id, ["空中喊话支援"]))

    # 5. 入网认证
    print(f"agent_c join={agent_c.join_network(agent_c_id)}")

    # 6. 等待 B 发起协作请求，并接收 A 发布的 Location 话题
    time.sleep(DEFAULT_WAIT_TIMEOUT_SECONDS)

    # 7. 退出网络
    print(agent_c.logout_network(agent_c_id))

    # 8. 去注册
    print(agent_c.deregister_agent(agent_c_id, "demo completed"))


if __name__ == "__main__":
    main()
