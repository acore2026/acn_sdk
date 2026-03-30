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


def push_ws_message(agent_id: str, message: dict) -> None:
    with httpx.Client(timeout=5.0, trust_env=False) as client:
        response = client.post(
            "http://127.0.0.1:9002/debug/ws-message",
            json={"agent_id": agent_id, "message": message},
        )
    response.raise_for_status()


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

    push_ws_message(
        collaborator_id,
        {
            "type": "TASK_REQUEST_COLLABORATION",
            "timestamp": "2026-03-30T00:00:00Z",
            "payload": {
                "src_agent_id": "ARF",
                "dst_agent_id": collaborator_id,
                "task_id": task_id,
                "task_description": "协同声光驱离",
                "agent_card": {"agent_id": initiator_id, "skill": ["可疑人员识别", "目标跟踪"]},
            },
        },
    )
    collaborator.poll_network_message()
    print(collaborator.accept_task_collaboration(collaborator_id, task_id))

    push_ws_message(
        initiator_id,
        {
            "type": "DISCOVER_RESULT",
            "timestamp": "2026-03-30T00:00:00Z",
            "payload": {
                "src_agent_id": "ARF",
                "dst_agent_id": initiator_id,
                "discover_result": [collaborator_id],
            },
        },
    )
    initiator.poll_network_message()

    print(initiator.start_task(initiator_id, collaborator_id, task_id, "协同声光驱离"))
    push_ws_message(
        collaborator_id,
        {
            "type": "START_TASK",
            "timestamp": "2026-03-30T00:00:00Z",
            "payload": {
                "src_agent_id": initiator_id,
                "dst_agent_id": collaborator_id,
                "task_id": task_id,
                "task_description": "协同声光驱离",
            },
        },
    )
    collaborator.poll_network_message()
    collaborator.request_task_execution(collaborator_id, "协同声光驱离", task_id=task_id)

    push_ws_message(
        collaborator_id,
        {
            "type": "SUBSCRIBE_TRACK",
            "timestamp": "2026-03-30T00:00:00Z",
            "payload": {
                "src_agent_id": initiator_id,
                "task_id": task_id,
                "track_list": [{"namespace": f"/{task_id}/{initiator_id}", "track": "Location"}],
            },
        },
    )
    collaborator.poll_network_message()
    time.sleep(0.2)

    initiator.task_info_report(initiator_id, task_id, "Location", current_timestamp_bytes())
    collaborator.moq_sub_client.pump(1.0)

    collaborator.request_terminate_task(collaborator_id, task_id, "demo finished")
    collaborator.logout_network(collaborator_id)
    initiator.logout_network(initiator_id)
    collaborator.deregister_robot(collaborator_id, "demo completed")
    initiator.deregister_robot(initiator_id, "demo completed")


if __name__ == "__main__":
    main()
