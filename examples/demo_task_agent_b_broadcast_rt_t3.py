from __future__ import annotations

import time
import threading

from acn_sdk import AcnSDK, AgentInfo

DEFAULT_WAIT_TIMEOUT_SECONDS = 150.0


def main() -> None:
    # 1. 初始化 B：先参加 A 的任务，再发起对 C 的协作请求
    agent_b = AcnSDK(
        agent_name="BridgeRobotT3B"
    )

    # 2. 申请 B 的数字身份
    agent_b_ok, agent_b_id = agent_b.register_agent_info(
        AgentInfo(
            name="BridgeRobotT3B",
            owner="13800138111",
            description="RobotDogModel, SN654321, B joins A and requests C",
            priority=4,
            metadata={"region": "CN", "role": "bridge_collaborator", "demo": "t3"},
        )
    )
    if not agent_b_ok:
        raise RuntimeError(agent_b_id)
    print(f"agent_b_id={agent_b_id}")
    print(f"agent_b local agent_info={agent_b.query_agent_info(agent_b_id)}")
    print(f"agent_b owner agents={agent_b.query_agent_list('13800138111')}")

    task_id_holder: dict[str, str] = {"value": ""}
    b_to_c_started = threading.Event()
    track_message_count: dict[str, int] = {"value": 0}
    requested_c_collaboration = threading.Event()

    # 3. 注册回调
    def agent_b_on_task_collaboration_request(payload: dict) -> None:
        print(f"[BridgeRobotT3B] on_task_collaboration_request payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        print(agent_b.accept_task_collaboration(agent_b_id, task_id))

    def agent_b_on_discover_result_received(payload: dict) -> None:
        print(f"[BridgeRobotT3B] on_discover_result_received payload={payload}")
        collaborator_candidates = payload.get("discover_result", [])
        if not collaborator_candidates:
            raise RuntimeError("discover_result is empty")
        task_id = task_id_holder["value"]
        if not task_id:
            raise RuntimeError("task_id is not initialized")
        result = agent_b.start_task_collaboration(
            agent_b_id,
            collaborator_candidates[0],
            task_id,
            "B发起请求，C参加",
        )
        print(f"[BridgeRobotT3B] start_task_collaboration B->C result={result}")
        b_to_c_started.set()

    def agent_b_on_task_start_command(payload: dict) -> None:
        print(f"[BridgeRobotT3B] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        print(
            agent_b.request_task_execution(
                agent_b_id,
                payload["task_description"],
                task_id=task_id,
            )
        )

    def agent_b_on_terminate_task_received(payload: dict) -> None:
        print(f"[BridgeRobotT3B] on_terminate_task_received payload={payload}")
        task_id = payload.get("task_id")
        reason = payload.get("reason", "")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("task_id is not available in TASK_TERMINATION payload")
        result = agent_b.request_terminate_task(agent_b_id, task_id, reason)
        print(f"[BridgeRobotT3B] request_terminate_task result={result}")

    def agent_b_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")
        track_message_count["value"] += 1
        if track_message_count["value"] != 3 or requested_c_collaboration.is_set():
            return

        task_id = task_id_holder["value"]
        if not task_id:
            raise RuntimeError("task_id is not initialized")
        requested_c_collaboration.set()
        print(
            agent_b.request_task_collaboration(
                agent_b_id,
                task_id,
                ["空中喊话支援"],
            )
        )

    agent_b.register_callbacks(
        on_task_collaboration_request=agent_b_on_task_collaboration_request,
        on_discover_result_received=agent_b_on_discover_result_received,
        on_task_start_command=agent_b_on_task_start_command,
        on_terminate_task_received=agent_b_on_terminate_task_received,
        on_message_received=agent_b_on_message_received,
    )

    # 4. 能力注册：B 可被 A 发现，也可作为发起方寻找 C
    print(agent_b.register_agent_attribute(agent_b_id, ["现场声光处置", "协作转发"]))

    # 5. 入网认证
    print(f"agent_b join={agent_b.join_network(agent_b_id)}")

    # 6. 等待 A 发起协作、B 收到第 3 条 track 后发起 C 协作、以及 A 广播终止任务
    if not b_to_c_started.wait(DEFAULT_WAIT_TIMEOUT_SECONDS):
        raise RuntimeError("Timed out waiting for C DISCOVER_RESULT.")
    time.sleep(DEFAULT_WAIT_TIMEOUT_SECONDS)

    # 7. 退出网络
    print(agent_b.logout_network(agent_b_id))

    # 8. 去注册
    print(agent_b.deregister_agent(agent_b_id, "demo completed"))


if __name__ == "__main__":
    main()
