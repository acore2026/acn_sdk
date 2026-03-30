from __future__ import annotations

import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from acn_sdk import AcnSDK, RobotInfo
from acn_sdk.config import SDKConfig


def on_message(agent_name: str, message_type: str, payload: dict) -> None:
    print(f"[{agent_name}] callback message_type={message_type} payload={payload}")


def _post_agent_gw_debug(path: str, payload: dict) -> None:
    with httpx.Client(timeout=5.0, trust_env=False) as client:
        response = client.post(f"http://127.0.0.1:9002{path}", json=payload)
    response.raise_for_status()


def push_task_request_collaboration(
    collaborator_agent_id: str,
    initiator_agent_id: str,
    task_id: str,
    task_description: str,
    initiator_skills: list[str],
) -> None:
    _post_agent_gw_debug(
        "/debug/task-request-collaboration",
        {
            "collaborator_agent_id": collaborator_agent_id,
            "initiator_agent_id": initiator_agent_id,
            "task_id": task_id,
            "task_description": task_description,
            "initiator_skills": initiator_skills,
        },
    )


def push_discover_result(initiator_agent_id: str, collaborator_ids: list[str]) -> None:
    _post_agent_gw_debug(
        "/debug/discover-result",
        {
            "initiator_agent_id": initiator_agent_id,
            "collaborator_ids": collaborator_ids,
        },
    )


def push_start_task(
    collaborator_agent_id: str,
    initiator_agent_id: str,
    task_id: str,
    task_description: str,
) -> None:
    _post_agent_gw_debug(
        "/debug/start-task",
        {
            "collaborator_agent_id": collaborator_agent_id,
            "initiator_agent_id": initiator_agent_id,
            "task_id": task_id,
            "task_description": task_description,
        },
    )


def push_subscribe_track(
    subscriber_agent_id: str,
    publisher_agent_id: str,
    task_id: str,
    topic: str,
) -> None:
    _post_agent_gw_debug(
        "/debug/subscribe-track",
        {
            "subscriber_agent_id": subscriber_agent_id,
            "publisher_agent_id": publisher_agent_id,
            "task_id": task_id,
            "topic": topic,
        },
    )


def build_config(base_dir: Path, moq_pub_port: int, moq_sub_port: int, identity_name: str) -> Path:
    config = SDKConfig.model_validate(
        {
            "sdk": {
                "http_port": 8001,
                "ws_port": 8002,
                "moq_pub_port": moq_pub_port,
                "moq_sub_port": moq_sub_port,
            },
            "network": {
                "network_ip": "127.0.0.1",
                "acn_agent_port": 9010,
                "arf_port": 9001,
                "agent_gw_ws_port": 9002,
                "agent_gw_moq_port": 9003,
                "web_ui_port": 9004,
                "path": "/ws",
            },
            "storage": {
                "identity_file": str(base_dir / identity_name / "identity.json"),
                "private_key_file": str(base_dir / identity_name / "keys" / "private.pem"),
                "public_key_file": str(base_dir / identity_name / "keys" / "public.pem"),
                "log_dir": str(base_dir / identity_name / "logs"),
            },
            "log_level": "INFO",
        }
    )
    config_path = base_dir / identity_name / "config.yaml"
    config.save(config_path)
    return config_path


def current_timestamp_bytes() -> bytes:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z").encode("utf-8")


def report_task_info_for_duration(
    sdk: AcnSDK,
    agent_id: str,
    task_id: str,
    topic: str,
    duration_seconds: float,
    interval_seconds: float = 1.0,
) -> None:
    deadline = time.monotonic() + duration_seconds
    while True:
        response = sdk.task_info_report(agent_id, task_id, topic, current_timestamp_bytes())
        print(response)
        if time.monotonic() >= deadline:
            break
        time.sleep(interval_seconds)


def main() -> None:
    base_dir = Path(tempfile.mkdtemp(prefix="acn-sdk-demo-"))
    print(f"demo_runtime_dir={base_dir}")
    initiator_config = build_config(base_dir, moq_pub_port=8103, moq_sub_port=8104, identity_name="initiator")
    collaborator_config = build_config(base_dir, moq_pub_port=8203, moq_sub_port=8204, identity_name="collaborator")

    initiator = AcnSDK(
        robot_name="AliceAgent",
        config_path=initiator_config,
        on_message_received=lambda msg_type, payload: on_message("AliceAgent", msg_type, payload),
    )
    collaborator = AcnSDK(
        robot_name="RobotDog",
        config_path=collaborator_config,
        on_message_received=lambda msg_type, payload: on_message("RobotDog", msg_type, payload),
    )

    initiator_id = initiator.register_agent_info(
        RobotInfo(
            name="AliceAgent",
            owner="13800138000",
            description="AgentModel-X, SN123456",
            priority=5,
            metadata={"region": "CN", "role": "initiator"},
        )
    )
    collaborator_id = collaborator.register_agent_info(
        RobotInfo(
            name="RobotDog",
            owner="13800138111",
            description="RobotDogModel, SN654321",
            priority=4,
            metadata={"region": "CN", "role": "collaborator"},
        )
    )
    print(f"initiator_id={initiator_id}")
    print(f"collaborator_id={collaborator_id}")

    initiator.register_agent_attribute(initiator_id, ["可疑人员识别", "目标跟踪"])
    collaborator.register_agent_attribute(collaborator_id, ["声光驱离"])

    print(f"initiator join={initiator.join_network(initiator_id)}")
    print(f"collaborator join={collaborator.join_network(collaborator_id)}")

    task_id = initiator.request_task_execution(initiator_id, "可疑人员驱离")
    print(f"task_id={task_id}")
    print(initiator.task_info_report(initiator_id, task_id, "Location", current_timestamp_bytes()))
    time.sleep(0.2)

    print(initiator.request_task_collaboration(initiator_id, task_id, ["声光驱离"]))

    push_task_request_collaboration(
        collaborator_agent_id=collaborator_id,
        initiator_agent_id=initiator_id,
        task_id=task_id,
        task_description="协同声光驱离",
        initiator_skills=["可疑人员识别", "目标跟踪"],
    )
    time.sleep(0.2)
    print(collaborator.accept_task_collaboration(collaborator_id, task_id))

    push_discover_result(initiator_agent_id=initiator_id, collaborator_ids=[collaborator_id])
    time.sleep(0.2)

    print(initiator.start_task(initiator_id, collaborator_id, task_id, "协同声光驱离"))
    push_start_task(
        collaborator_agent_id=collaborator_id,
        initiator_agent_id=initiator_id,
        task_id=task_id,
        task_description="协同声光驱离",
    )
    time.sleep(0.2)
    collaborator.request_task_execution(collaborator_id, "协同声光驱离", task_id=task_id)

    push_subscribe_track(
        subscriber_agent_id=collaborator_id,
        publisher_agent_id=initiator_id,
        task_id=task_id,
        topic="Location",
    )
    time.sleep(0.2)

    report_task_info_for_duration(initiator, initiator_id, task_id, "Location", duration_seconds=30.0)
    collaborator.moq_sub_client.pump(1.0)

    collaborator.request_terminate_task(collaborator_id, task_id, "demo finished")
    collaborator.logout_network(collaborator_id)
    initiator.logout_network(initiator_id)
    collaborator.deregister_robot(collaborator_id, "demo completed")
    initiator.deregister_robot(initiator_id, "demo completed")


if __name__ == "__main__":
    main()
