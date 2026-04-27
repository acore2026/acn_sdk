from __future__ import annotations

import sys
import time
from pathlib import Path
from acn_sdk import AcnSDK, AgentInfo

DEFAULT_WAIT_TIMEOUT_SECONDS = 80.0


def main() -> None:
    # 1. 初始化机器狗SDK
    collaborator = AcnSDK(
        agent_name="RobotDog"
    )

    # 2. 申请 collaborator 数字身份，并确认本地 agent 信息可用（查询非必须）
    collaborator_ok, collaborator_id = collaborator.register_agent_info(
        AgentInfo(
            name="RobotDog",
            owner="13800138111",
            description="RobotDogModel, SN654321",
            priority=4,
            metadata={"region": "CN", "role": "collaborator"},
        )
    )
    if not collaborator_ok:
        raise RuntimeError(collaborator_id)
    print(f"collaborator_id={collaborator_id}")
    print(f"collaborator local agent_info={collaborator.query_agent_info(collaborator_id)}")
    print(f"collaborator owner agents={collaborator.query_agent_list('13800138111')}")

    task_id_holder: dict[str, str] = {"value": ""}

    # 3. 注册回调
    def collaborator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[RobotDog] on_task_collaboration_request payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.accept_task_collaboration(collaborator_id, task_id)

    def collaborator_on_discover_result_received(payload: dict) -> None:
        print(f"[RobotDog] on_discover_result_received payload={payload}")
        collaborator_candidates = payload.get("discover_result", [])
        if not collaborator_candidates:
            raise RuntimeError("discover_result is empty")
        task_id = task_id_holder["value"]
        if not task_id:
            raise RuntimeError("task_id is not initialized")
        collaborator.start_task_collaboration(
            collaborator_id,
            collaborator_candidates[0],
            task_id,
            "协同声光驱离",
        )

    def collaborator_on_task_start_command(payload: dict) -> None:
        print(f"[RobotDog] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.request_task_execution(
            collaborator_id,
            payload["task_description"],
            task_id=task_id,
        )

    def collaborator_on_terminate_task_received(payload: dict) -> None:
        print(f"[RobotDog] on_terminate_task_received payload={payload}")
        task_id = payload.get("task_id")
        reason = payload.get("reason", "")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("task_id is not available in TASK_TERMINATION payload")
        result = collaborator.request_terminate_task(collaborator_id, task_id, reason)
        print(f"[RobotDog] request_terminate_task result={result}")

    def collaborator_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    collaborator.register_callbacks(
        on_task_collaboration_request=collaborator_on_task_collaboration_request,
        on_discover_result_received=collaborator_on_discover_result_received,
        on_task_start_command=collaborator_on_task_start_command,
        on_terminate_task_received=collaborator_on_terminate_task_received,
        on_message_received=collaborator_on_message_received,
    )

    # 4. 能力注册
    print(collaborator.register_agent_attribute(collaborator_id, ["声光驱离"]))

    # 5. 入网认证
    print(f"collaborator join={collaborator.join_network(collaborator_id)}")

    # 6. 等待无人机发起协作任务
    time.sleep(DEFAULT_WAIT_TIMEOUT_SECONDS)

    # 7. 等待终止任务
    print(collaborator.broadcast_terminate_task(collaborator_id, task_id_holder["value"], "demo finished"))
    time.sleep(5)
    # task_id = task_id_holder["value"]
    # if task_id:
    #     print(collaborator.request_terminate_task(collaborator_id, task_id, "demo finished"))

    # 8. 退出网络
    print(collaborator.logout_network(collaborator_id))

    # 9. 去注册
    print(collaborator.deregister_agent(collaborator_id, "demo completed"))


if __name__ == "__main__":
    main()
