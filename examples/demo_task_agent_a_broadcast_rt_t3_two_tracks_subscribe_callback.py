from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

from acn_sdk import AcnSDK, AgentInfo

DEFAULT_WAIT_TIMEOUT_SECONDS = 120.0
DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS = 10.0
DEFAULT_WAIT_TERMINATE_TASK_SECONDS = 10.0
TOPIC_POSITION = "Position"
TOPIC_STATUS = "Status"
TASK_TOPICS = (TOPIC_POSITION, TOPIC_STATUS)


def task_info_bytes(topic: str, *, seq: int, reported_at: str) -> bytes:
    if topic == TOPIC_POSITION:
        payload: dict[str, Any] = {
            "longitude": 116.404 + seq * 0.0001,
            "latitude": 39.915 + seq * 0.0001,
            "altitude": 50.5,
            "seq": seq,
            "reported_at": reported_at,
        }
    elif topic == TOPIC_STATUS:
        payload = {
            "battery_percent": max(0, 95 - seq),
            "state": "tracking",
            "seq": seq,
            "reported_at": reported_at,
        }
    else:
        raise ValueError(f"Unsupported topic: {topic}")
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def report_task_info_rounds(
    sdk: Any,
    agent_id: str,
    task_id: str,
    count: int,
    interval_seconds: float = 1.0,
    start_seq: int = 1,
) -> None:
    for offset in range(count):
        seq = start_seq + offset
        reported_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        for topic in TASK_TOPICS:
            response = sdk.task_info_report(
                agent_id,
                task_id,
                topic,
                task_info_bytes(topic, seq=seq, reported_at=reported_at),
            )
            print(response)
        if offset < count - 1:
            time.sleep(interval_seconds)


def main() -> None:
    # 1. 初始化 A：任务发起方和两个 track 的发布方
    agent_a = AcnSDK(agent_name="AliceAgentT3A2Tracks")

    # 2. 申请 A 的数字身份
    agent_a_ok, agent_a_id = agent_a.register_agent_info(
        AgentInfo(
            name="AliceAgentT3A2Tracks",
            owner="13800138000",
            description="AgentModel-X, SN123456, A publishes Position and Status tracks",
            priority=5,
            metadata={"region": "CN", "role": "publisher_initiator", "demo": "t3_two_tracks"},
        )
    )
    if not agent_a_ok:
        raise RuntimeError(agent_a_id)
    print(f"agent_a_id={agent_a_id}")
    print(f"agent_a local agent_info={agent_a.query_agent_info(agent_a_id)}")
    print(f"agent_a owner agents={agent_a.query_agent_list('13800138000')}")

    task_id_holder: dict[str, str] = {"value": ""}
    a_to_b_started = threading.Event()

    # 3. 注册回调
    def agent_a_on_task_collaboration_request(payload: dict) -> None:
        print(f"[AliceAgentT3A2Tracks] on_task_collaboration_request payload={payload}")
        task_id = payload.get("task_id")
        if isinstance(task_id, str) and task_id:
            task_id_holder["value"] = task_id
            print(agent_a.accept_task_collaboration(agent_a_id, task_id))

    def agent_a_on_discover_result_received(payload: dict) -> None:
        print(f"[AliceAgentT3A2Tracks] on_discover_result_received payload={payload}")
        collaborator_candidates = payload.get("discover_result", [])
        if not collaborator_candidates:
            raise RuntimeError("discover_result is empty")
        task_id = task_id_holder["value"]
        if not task_id:
            raise RuntimeError("task_id is not initialized")
        result = agent_a.start_task_collaboration(
            agent_a_id,
            collaborator_candidates[0],
            task_id,
            "A发起请求，B参加并接收Position/Status",
        )
        print(f"[AliceAgentT3A2Tracks] start_task_collaboration A->B result={result}")
        a_to_b_started.set()

    def agent_a_on_task_start_command(payload: dict) -> None:
        print(f"[AliceAgentT3A2Tracks] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        print(agent_a.request_task_execution(agent_a_id, payload["task_description"], task_id=task_id))

    def agent_a_on_terminate_task_received(payload: dict) -> None:
        print(f"[AliceAgentT3A2Tracks] on_terminate_task_received payload={payload}")
        task_id = payload.get("task_id")
        reason = payload.get("reason", "")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("task_id is not available in TASK_TERMINATION payload")
        result = agent_a.request_terminate_task(agent_a_id, task_id, reason)
        print(f"[AliceAgentT3A2Tracks] request_terminate_task result={result}")

    def agent_a_on_subscribe_track_received(payload: dict) -> dict[str, str]:
        print(f"[AliceAgentT3A2Tracks] on_subscribe_track_received payload={payload}")
        track_modes = {
            f"{track_info['namespace']}::{track_info['track']}": "subscribe"
            for track_info in payload.get("track_list", [])
        }
        print(f"[AliceAgentT3A2Tracks] subscribe track modes={track_modes}")
        return track_modes

    def agent_a_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    agent_a.register_callbacks(
        on_task_collaboration_request=agent_a_on_task_collaboration_request,
        on_discover_result_received=agent_a_on_discover_result_received,
        on_task_start_command=agent_a_on_task_start_command,
        on_terminate_task_received=agent_a_on_terminate_task_received,
        on_subscribe_track_received=agent_a_on_subscribe_track_received,
        on_message_received=agent_a_on_message_received,
    )

    # 4. 能力注册
    print(agent_a.register_agent_attribute(agent_a_id, ["可疑人员识别", "目标跟踪", "位置发布", "状态发布"]))

    # 5. 入网认证
    print(f"agent_a join={agent_a.join_network(agent_a_id)}")

    # 6. A 发起任务，并先发布一次 Position 和 Status，让后续协作方能看到两个 track
    time.sleep(15)
    task_ok, task_id = agent_a.request_task_execution(agent_a_id, "可疑人员协同处置-双Track")
    if not task_ok:
        raise RuntimeError(task_id)
    task_id_holder["value"] = task_id
    print(f"task_id={task_id}")
    report_task_info_rounds(agent_a, agent_a_id, task_id, count=1, start_seq=1)

    # 7. A 请求 B 参加；B 收到第 3 条 Position 后继续请求 C 参加
    print(agent_a.request_task_collaboration(agent_a_id, task_id, ["现场声光处置"]))
    if not a_to_b_started.wait(DEFAULT_WAIT_TIMEOUT_SECONDS):
        raise RuntimeError("Timed out waiting for B DISCOVER_RESULT.")

    time.sleep(DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS)
    report_task_info_rounds(agent_a, agent_a_id, task_id, count=3, start_seq=2)

    # 8. 等待 B->C 协作链建立，C 对 Position 使用 fetch，对 Status 使用 subscribe
    time.sleep(DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS)
    report_task_info_rounds(agent_a, agent_a_id, task_id, count=10, start_seq=5)

    # 9. 广播终止任务
    print(agent_a.broadcast_terminate_task(agent_a_id, task_id, "demo finished"))
    time.sleep(DEFAULT_WAIT_TERMINATE_TASK_SECONDS)

    # 10. 退出网络
    print(agent_a.logout_network(agent_a_id))

    # 11. 去注册
    print(agent_a.deregister_agent(agent_a_id, "demo completed"))


if __name__ == "__main__":
    main()
