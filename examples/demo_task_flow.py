from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import httpx

from acn_sdk import AcnSDK, RobotInfo
from acn_sdk.config import SDKConfig


def on_moq_message_received(agent_name: str, namespace: str, track: str, payload: bytes) -> None:
    print(f"[{agent_name}] moq_message namespace={namespace} track={track} payload={payload!r}")


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


def build_config(base_dir: Path, identity_name: str) -> Path:
    config = SDKConfig.model_validate(
        {
            "network": {
                "network_ip": "127.0.0.1",
                "acn_agent_port": 9010,
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


def current_location_bytes() -> bytes:
    payload = {
        "longitude": 116.404,
        "latitude": 39.915,
        "altitude": 50.5,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


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
        response = sdk.task_info_report(agent_id, task_id, topic, current_location_bytes())
        print(response)
        if time.monotonic() >= deadline:
            break
        time.sleep(interval_seconds)


def main() -> None:
    base_dir = Path(tempfile.mkdtemp(prefix="acn-sdk-demo-"))
    print(f"demo_runtime_dir={base_dir}")
    initiator_config = build_config(base_dir, identity_name="initiator")
    collaborator_config = build_config(base_dir, identity_name="collaborator")

    initiator = AcnSDK(
        robot_name="AliceAgent",
        config_path=initiator_config,
    )
    collaborator = AcnSDK(
        robot_name="RobotDog",
        config_path=collaborator_config,
    )

    initiator_ok, initiator_id = initiator.register_agent_info(
        RobotInfo(
            name="AliceAgent",
            owner="13800138000",
            description="AgentModel-X, SN123456",
            priority=5,
            metadata={"region": "CN", "role": "initiator"},
        )
    )
    collaborator_ok, collaborator_id = collaborator.register_agent_info(
        RobotInfo(
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

    def initiator_on_discover_result_received(payload: dict) -> None:
        print(f"[AliceAgent] on_discover_result_received payload={payload}")
        collaborator_candidates = payload.get("discover_result", [])
        if not collaborator_candidates:
            raise RuntimeError("discover_result is empty")
        initiator.start_task_collaboration(
            initiator_id,
            collaborator_candidates[0],
            task_id,
            "协同声光驱离",
        )

    def collaborator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[RobotDog] on_task_collaboration_request payload={payload}")
        collaborator.accept_task_collaboration(collaborator_id, task_id, payload["src_agent_id"])

    def collaborator_on_task_start_command(payload: dict) -> None:
        print(f"[RobotDog] on_task_start_command payload={payload}")
        collaborator.request_task_execution(
            collaborator_id,
            payload["task_description"],
            task_id=payload["task_id"],
        )

    initiator.register_callbacks(
        on_discover_result_received=initiator_on_discover_result_received,
        on_moq_message_received=lambda namespace, track, payload: on_moq_message_received(
            "AliceAgent", namespace, track, payload
        ),
    )
    collaborator.register_callbacks(
        on_task_collaboration_request=collaborator_on_task_collaboration_request,
        on_task_start_command=collaborator_on_task_start_command,
        on_moq_message_received=lambda namespace, track, payload: on_moq_message_received(
            "RobotDog", namespace, track, payload
        ),
    )

    print(initiator.register_agent_attribute(initiator_id, ["可疑人员识别", "目标跟踪"]))
    print(collaborator.register_agent_attribute(collaborator_id, ["声光驱离"]))

    print(f"initiator join={initiator.join_network(initiator_id)}")
    print(f"collaborator join={collaborator.join_network(collaborator_id)}")

    task_ok, task_id = initiator.request_task_execution(initiator_id, "可疑人员驱离")
    if not task_ok:
        raise RuntimeError(task_id)
    print(f"task_id={task_id}")
    print(initiator.task_info_report(initiator_id, task_id, "Location", current_location_bytes()))
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

    push_discover_result(initiator_agent_id=initiator_id, collaborator_ids=[collaborator_id])
    time.sleep(0.2)

    push_start_task(
        collaborator_agent_id=collaborator_id,
        initiator_agent_id=initiator_id,
        task_id=task_id,
        task_description="协同声光驱离",
    )
    time.sleep(0.2)

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
