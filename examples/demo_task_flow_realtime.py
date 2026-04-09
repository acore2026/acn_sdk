from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, AgentInfo
from acn_sdk.config import SDKConfig

DEFAULT_RUNTIME_ROOT = Path(tempfile.gettempdir()) / "acn-sdk-demo-realtime"
REPO_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


# 运行辅助函数。
# 这些函数替代了旧的 demo_task_shared 导入，让整个 demo 流程保持自包含。
def build_config_from_repo(base_dir: Path, identity_name: str, repo_config_path: Path = REPO_CONFIG_PATH) -> Path:
    # 先读取仓库配置，再把所有运行产物重定向到临时 demo 目录。
    config = SDKConfig.load(repo_config_path)
    config.storage.identity_file = str(base_dir / identity_name / "identity.json")
    config.storage.private_key_file = str(base_dir / identity_name / "keys" / "private.pem")
    config.storage.public_key_file = str(base_dir / identity_name / "keys" / "public.pem")
    config.storage.log_dir = str(base_dir / identity_name / "logs")
    config_path = base_dir / identity_name / "config.yaml"
    config.save(config_path)
    return config_path


def current_location_bytes(*, seq: int | None = None, reported_at: str | None = None) -> bytes:
    # realtime 演示持续发送同一位置，只变化序号和时间戳。
    payload = {
        "longitude": 116.404,
        "latitude": 39.915,
        "altitude": 50.5,
    }
    if seq is not None:
        payload["seq"] = seq
    if reported_at is not None:
        payload["reported_at"] = reported_at
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def report_task_info_for_duration(
    sdk: Any,
    agent_id: str,
    task_id: str,
    topic: str,
    duration_seconds: float,
    interval_seconds: float = 1.0,
    start_seq: int = 1,
) -> None:
    # 这个循环就是实时遥测流，用来维持 demo 期间的任务活性。
    seq = start_seq
    deadline = time.monotonic() + duration_seconds
    while True:
        reported_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        response = sdk.task_info_report(
            agent_id,
            task_id,
            topic,
            current_location_bytes(seq=seq, reported_at=reported_at),
        )
        print(response)
        seq += 1
        if time.monotonic() >= deadline:
            break
        time.sleep(interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the task demo without stubbing intermediate messages.")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--report-duration", type=float, default=30.0)
    parser.add_argument("--wait-timeout", type=float, default=120.0)
    return parser.parse_args()


def _wait_event(event: threading.Event, timeout_seconds: float, description: str) -> None:
    if not event.wait(timeout_seconds):
        raise RuntimeError(f"Timed out waiting for {description}")


def main() -> None:
    args = parse_args()
    base_dir = Path(args.runtime_root)
    base_dir.mkdir(parents=True, exist_ok=True)
    print(f"demo_runtime_dir={base_dir}")

    # 第 1 步：在 realtime 消息交互开始前，先准备两个 agent 的配置。
    initiator_config = build_config_from_repo(base_dir, identity_name="initiator")
    collaborator_config = build_config_from_repo(base_dir, identity_name="collaborator")

    initiator = AcnSDK(
        agent_name="AliceAgent",
        config_path=initiator_config,
    )
    collaborator = AcnSDK(
        agent_name="RobotDog",
        config_path=collaborator_config,
    )

    # 第 2 步：注册两个 agent，并确认返回的 ID 再继续。
    initiator_ok, initiator_id = initiator.register_agent_info(
        AgentInfo(
            name="AliceAgent",
            owner="13800138000",
            description="AgentModel-X, SN123456",
            priority=5,
            metadata={"region": "CN", "role": "initiator"},
        )
    )
    collaborator_ok, collaborator_id = collaborator.register_agent_info(
        AgentInfo(
            name="RobotDog",
            owner="13800138111",
            description="RobotDogModel, SN654321",
            priority=4,
            metadata={"region": "CN", "role": "collaborator"},
        )
    )
    if not initiator_ok:
        raise RuntimeError(initiator_id)
    if not collaborator_ok:
        raise RuntimeError(collaborator_id)
    print(f"initiator_id={initiator_id}")
    print(f"collaborator_id={collaborator_id}")

    task_id_holder: dict[str, str] = {"value": ""}
    collaboration_request_received = threading.Event()
    discover_result_received = threading.Event()
    task_start_received = threading.Event()

    # initiator 在这个阶段只记录收到的协同请求。
    def initiator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[AliceAgent] on_task_collaboration_request payload={payload}")

    # discovery 返回后，initiator 选择第一个协同候选并启动联合任务。
    def initiator_on_discover_result_received(payload: dict) -> None:
        print(f"[AliceAgent] on_discover_result_received payload={payload}")
        collaborator_candidates = payload.get("discover_result", [])
        if not collaborator_candidates:
            raise RuntimeError("discover_result is empty")
        task_id = task_id_holder["value"]
        if not task_id:
            raise RuntimeError("task_id is not initialized")
        initiator.start_task_collaboration(
            initiator_id,
            collaborator_candidates[0],
            task_id,
            "声光驱离",
        )
        discover_result_received.set()

    # collaborator 接受请求后，从空闲状态切换到任务执行状态。
    def collaborator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[RobotDog] on_task_collaboration_request payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.accept_task_collaboration(collaborator_id, task_id)
        collaboration_request_received.set()

    # 在 collaborator 侧打印 discovery 结果，便于观察流程。
    def collaborator_on_discover_result_received(payload: dict) -> None:
        print(f"[RobotDog] on_discover_result_received payload={payload}")

    # 启动命令到来后，collaborator 才真正开始响应任务。
    def collaborator_on_task_start_command(payload: dict) -> None:
        print(f"[RobotDog] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.request_task_execution(
            collaborator_id,
            payload["task_description"],
            task_id=task_id,
        )
        task_start_received.set()

    def initiator_on_task_start_command(payload: dict) -> None:
        print(f"[AliceAgent] on_task_start_command payload={payload}")

    # 两个 agent 都打印 MoQ 载荷，方便在 demo 中观察实时传输。
    def initiator_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    def collaborator_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    # 第 3 步：绑定驱动 realtime 协同状态机的回调。
    initiator.register_callbacks(
        on_task_collaboration_request=initiator_on_task_collaboration_request,
        on_discover_result_received=initiator_on_discover_result_received,
        on_task_start_command=initiator_on_task_start_command,
        on_message_received=initiator_on_message_received,
    )
    collaborator.register_callbacks(
        on_task_collaboration_request=collaborator_on_task_collaboration_request,
        on_discover_result_received=collaborator_on_discover_result_received,
        on_task_start_command=collaborator_on_task_start_command,
        on_message_received=collaborator_on_message_received,
    )

    # 第 4 步：发布 agent 能力并加入网络，然后再进入任务执行阶段。
    print(initiator.register_agent_attribute(initiator_id, ["可疑人员识别", "目标跟踪"]))
    print(collaborator.register_agent_attribute(collaborator_id, ["声光驱离"]))
    print(f"initiator local agent_info={initiator.query_agent_info(initiator_id)}")
    print(f"collaborator remote agent_info={initiator.query_agent_info(collaborator_id)}")
    print(f"initiator owner agents={initiator.query_agent_list('13800138000')}")
    print(f"collaborator owner agents={collaborator.query_agent_list('13800138111')}")

    print(f"initiator join={initiator.join_network(initiator_id)}")
    print(f"collaborator join={collaborator.join_network(collaborator_id)}")
    print(f"1 initiator local agent_info={initiator.query_agent_info(initiator_id)}")
    print(f"1 collaborator remote agent_info={initiator.query_agent_info(collaborator_id)}")

    # 第 5 步：启动任务，并立即发送第一条遥测数据。
    task_ok, task_id = initiator.request_task_execution(initiator_id, "可疑人员驱离")
    if not task_ok:
        raise RuntimeError(task_id)
    task_id_holder["value"] = task_id
    print(f"task_id={task_id}")
    first_reported_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    print(
        initiator.task_info_report(
            initiator_id,
            task_id,
            "Location",
            current_location_bytes(seq=1, reported_at=first_reported_at),
        )
    )

    # 第 6 步：请求协同，并等待完整握手流程结束。
    print(initiator.request_task_collaboration(initiator_id, task_id, ["声光驱离"]))
    _wait_event(collaboration_request_received, args.wait_timeout, "TASK_REQUEST_COLLABORATION")
    _wait_event(discover_result_received, args.wait_timeout, "DISCOVER_RESULT")
    _wait_event(task_start_received, args.wait_timeout, "START_TASK")

    # 第 7 步：在协同进行中持续发送遥测数据。
    report_task_info_for_duration(
        initiator,
        initiator_id,
        task_id,
        "Location",
        duration_seconds=args.report_duration,
        start_seq=2,
    )

    # 第 8 步：关闭两个 agent，并打印最终状态用于确认。
    collaborator.request_terminate_task(collaborator_id, task_id, "demo finished")
    collaborator.logout_network(collaborator_id)
    print(f"2. collaborator remote agent_info={initiator.query_agent_info(collaborator_id)}")
    initiator.request_terminate_task(initiator_id, task_id, "demo finished")
    initiator.logout_network(initiator_id)
    collaborator.deregister_agent(collaborator_id, "demo completed")
    initiator.deregister_agent(initiator_id, "demo completed")
    print(f"initiator local agent_info={initiator.query_agent_info(initiator_id)}")
    print(f"collaborator remote agent_info={initiator.query_agent_info(collaborator_id)}")
    print(f"initiator owner agents={initiator.query_agent_list('13800138000')}")
    print(f"collaborator owner agents={collaborator.query_agent_list('13800138111')}")


if __name__ == "__main__":
    main()
