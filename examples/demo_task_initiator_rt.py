from __future__ import annotations

import json
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, AgentInfo

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
DEFAULT_WAIT_TIMEOUT_SECONDS = 120.0
DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS = 5.0


def current_location_bytes(*, seq: int | None = None, reported_at: str | None = None) -> bytes:
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


def main() -> None:
    # 第 1 步：直接读取仓库里的固定配置，不再创建 session 目录或重写配置文件。
    initiator = AcnSDK(
        agent_name="AliceAgent",
        config_path=CONFIG_PATH,
    )

    # 第 2 步：注册 initiator 身份，并确认本地 agent 信息可用。
    initiator_ok, initiator_id = initiator.register_agent_info(
        AgentInfo(
            name="AliceAgent",
            owner="13800138000",
            description="AgentModel-X, SN123456",
            priority=5,
            metadata={"region": "CN", "role": "initiator"},
        )
    )
    if not initiator_ok:
        raise RuntimeError(initiator_id)
    print(f"initiator_id={initiator_id}")
    print(f"initiator local agent_info={initiator.query_agent_info(initiator_id)}")
    print(f"initiator owner agents={initiator.query_agent_list('13800138000')}")

    task_id_holder: dict[str, str] = {"value": ""}
    discover_result_received = threading.Event()

    # 第 3 步：注册回调，按任务协同流程推进 initiator 侧状态。
    def initiator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[AliceAgent] on_task_collaboration_request payload={payload}")

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
            "协同声光驱离",
        )
        discover_result_received.set()

    def initiator_on_task_start_command(payload: dict) -> None:
        print(f"[AliceAgent] on_task_start_command payload={payload}")

    def initiator_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    initiator.register_callbacks(
        on_task_collaboration_request=initiator_on_task_collaboration_request,
        on_discover_result_received=initiator_on_discover_result_received,
        on_task_start_command=initiator_on_task_start_command,
        on_message_received=initiator_on_message_received,
    )

    # 第 4 步：先发布能力，再加入网络，等待外部发起任务协同。
    print(initiator.register_agent_attribute(initiator_id, ["可疑人员识别", "目标跟踪"]))
    print(f"initiator join={initiator.join_network(initiator_id)}")

    # 第 5 步：申请任务，并先发一条定位样本，让协同流程尽快进入可观测状态。
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

    # 第 6 步：请求协同，等待 collaborator 侧回传 discover 结果后继续推进。
    print(initiator.request_task_collaboration(initiator_id, task_id, ["声光驱离"]))
    if not discover_result_received.wait(DEFAULT_WAIT_TIMEOUT_SECONDS):
        raise RuntimeError("Timed out waiting for DISCOVER_RESULT.")
    time.sleep(DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS)

    # 第 7 步：协同建立后，持续上报任务遥测数据。
    report_task_info_for_duration(
        initiator,
        initiator_id,
        task_id,
        "Location",
        duration_seconds=10.0,
        start_seq=2,
    )

    # 第 8 步：收尾，终止任务并退出网络。
    print(initiator.request_terminate_task(initiator_id, task_id, "demo finished"))
    print(initiator.logout_network(initiator_id))
    print(initiator.deregister_agent(initiator_id, "demo completed"))


if __name__ == "__main__":
    main()
