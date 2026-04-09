from __future__ import annotations

import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, AgentInfo

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
DEFAULT_WAIT_TIMEOUT_SECONDS = 120.0


def main() -> None:
    # 第 1 步：直接加载固定配置，省略命令行参数和临时 session 目录。
    collaborator = AcnSDK(
        agent_name="RobotDog",
        config_path=CONFIG_PATH,
    )

    # 第 2 步：注册 collaborator 身份，便于 initiator 发现。
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

    # 第 3 步：注册回调，收到任务协同请求后立刻接单。
    def collaborator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[RobotDog] on_task_collaboration_request payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.accept_task_collaboration(collaborator_id, task_id)

    def collaborator_on_discover_result_received(payload: dict) -> None:
        print(f"[RobotDog] on_discover_result_received payload={payload}")

    def collaborator_on_task_start_command(payload: dict) -> None:
        print(f"[RobotDog] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.request_task_execution(
            collaborator_id,
            payload["task_description"],
            task_id=task_id,
        )

    def collaborator_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    collaborator.register_callbacks(
        on_task_collaboration_request=collaborator_on_task_collaboration_request,
        on_discover_result_received=collaborator_on_discover_result_received,
        on_task_start_command=collaborator_on_task_start_command,
        on_message_received=collaborator_on_message_received,
    )

    # 第 4 步：发布能力并加入网络，然后保持在线等待 initiator 发起协同。
    print(collaborator.register_agent_attribute(collaborator_id, ["声光驱离"]))
    print(f"collaborator join={collaborator.join_network(collaborator_id)}")
    time.sleep(DEFAULT_WAIT_TIMEOUT_SECONDS)

    # 第 5 步：等待窗口结束后清理任务状态并退出网络。
    task_id = task_id_holder["value"]
    if task_id:
        print(collaborator.request_terminate_task(collaborator_id, task_id, "demo finished"))
    print(collaborator.logout_network(collaborator_id))
    print(collaborator.deregister_agent(collaborator_id, "demo completed"))


if __name__ == "__main__":
    main()
