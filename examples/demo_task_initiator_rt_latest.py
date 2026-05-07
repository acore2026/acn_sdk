from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

from acn_sdk import AcnSDK, AgentInfo

DEFAULT_WAIT_TIMEOUT_SECONDS = 120.0
DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS = 5.0
DEFAULT_WAIT_TERMINATE_TASK_SECONDS = 10.0
TOPIC_LOCATION = "Location"


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
    # 1. 初始化无人机SDK
    initiator = AcnSDK(
        agent_name="AliceAgent"
    )

    # 2. 申请 initiator 数字身份，并确认本地 agent 信息可用（查询非必须）
    initiator_ok, initiator_id = initiator.register_agent_info(
        AgentInfo(
            name="AliceAgent",
            owner="13800138000",
            description="AgentModel-X, SN123456",
            priority=5,
            metadata={"region": "CN", "role": "initiator", "demo": "rt_latest"},
        )
    )
    if not initiator_ok:
        raise RuntimeError(initiator_id)
    print(f"initiator_id={initiator_id}")
    print(f"initiator local agent_info={initiator.query_agent_info(initiator_id)}")
    print(f"initiator owner agents={initiator.query_agent_list('13800138000')}")

    task_id_holder: dict[str, str] = {"value": ""}
    discover_result_received = threading.Event()

    # 3. 注册回调
    def initiator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[AliceAgent] on_task_collaboration_request payload={payload}")
        task_id = payload.get("task_id")
        if isinstance(task_id, str) and task_id:
            task_id_holder["value"] = task_id
            print(initiator.accept_task_collaboration(initiator_id, task_id))

    def initiator_on_discover_result_received(payload: dict) -> None:
        print(f"[AliceAgent] on_discover_result_received payload={payload}")
        collaborator_candidates = payload.get("discover_result", [])
        if not collaborator_candidates:
            raise RuntimeError("discover_result is empty")
        task_id = task_id_holder["value"]
        if not task_id:
            raise RuntimeError("task_id is not initialized")
        result = initiator.start_task_collaboration(
            initiator_id,
            collaborator_candidates[0],
            task_id,
            "协同声光驱离",
        )
        print(f"[AliceAgent] start_task_collaboration result={result}")
        discover_result_received.set()

    def initiator_on_task_start_command(payload: dict) -> None:
        print(f"[AliceAgent] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        print(
            initiator.request_task_execution(
                initiator_id,
                payload["task_description"],
                task_id=task_id,
            )
        )

    def initiator_on_terminate_task_received(payload: dict) -> None:
        print(f"[AliceAgent] on_terminate_task_received payload={payload}")
        task_id = payload.get("task_id")
        reason = payload.get("reason", "")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("task_id is not available in TASK_TERMINATION payload")
        result = initiator.request_terminate_task(initiator_id, task_id, reason)
        print(f"[AliceAgent] request_terminate_task result={result}")

    def initiator_on_subscribe_track_received(payload: dict) -> dict[str, str]:
        print(f"[AliceAgent] on_subscribe_track_received payload={payload}")
        track_modes: dict[str, str] = {}
        for track_info in payload.get("track_list", []):
            namespace = track_info.get("namespace")
            track = track_info.get("track")
            if not isinstance(namespace, str) or not isinstance(track, str):
                continue
            mode = "fetch" if track == TOPIC_LOCATION else "subscribe"
            track_modes[f"{namespace}::{track}"] = mode
        print(f"[AliceAgent] subscribe track modes={track_modes}")
        return track_modes

    def initiator_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    print(
        initiator.register_callbacks(
            on_task_collaboration_request=initiator_on_task_collaboration_request,
            on_discover_result_received=initiator_on_discover_result_received,
            on_task_start_command=initiator_on_task_start_command,
            on_terminate_task_received=initiator_on_terminate_task_received,
            on_subscribe_track_received=initiator_on_subscribe_track_received,
            on_message_received=initiator_on_message_received,
        )
    )

    # 4. 能力注册
    print(initiator.register_agent_attribute(initiator_id, ["可疑人员识别", "目标跟踪"]))

    # 5. 入网认证
    print(f"initiator join={initiator.join_network(initiator_id)}")

    # 6. 请求执行任务
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
            TOPIC_LOCATION,
            current_location_bytes(seq=1, reported_at=first_reported_at),
        )
    )

    # 7. 请求协同，等待 collaborator 侧回传 discover 结果后继续推进
    print(initiator.request_task_collaboration(initiator_id, task_id, ["声光驱离"]))
    if not discover_result_received.wait(DEFAULT_WAIT_TIMEOUT_SECONDS):
        raise RuntimeError("Timed out waiting for DISCOVER_RESULT.")
    time.sleep(DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS)

    # 8. 协同建立后，持续上报任务遥测数据
    report_task_info_for_duration(
        initiator,
        initiator_id,
        task_id,
        TOPIC_LOCATION,
        duration_seconds=10.0,
        start_seq=2,
    )

    # 9. 终止任务：单独停止任务示例保留为注释，默认使用广播停止任务
    # print(initiator.request_terminate_task(initiator_id, task_id, "demo finished"))
    print(initiator.broadcast_terminate_task(initiator_id, task_id, "demo finished"))
    time.sleep(DEFAULT_WAIT_TERMINATE_TASK_SECONDS)

    # 10. 退出网络
    print(initiator.logout_network(initiator_id))

    # 11. 去注册
    print(initiator.deregister_agent(initiator_id, "demo completed"))


if __name__ == "__main__":
    main()
