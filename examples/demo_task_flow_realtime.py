from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, RobotInfo
from demo_task_shared import build_config, current_location_bytes, report_task_info_for_duration


def on_moq_message_received(agent_name: str, namespace: str, track: str, payload: bytes) -> None:
    print(f"[{agent_name}] moq_message namespace={namespace} track={track} payload={payload!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the task demo without stubbing intermediate messages.")
    parser.add_argument("--runtime-root", type=Path, default=Path(tempfile.gettempdir()) / "acn-sdk-demo-realtime")
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

    task_id_holder: dict[str, str] = {"value": ""}
    collaboration_request_received = threading.Event()
    discover_result_received = threading.Event()
    task_start_received = threading.Event()
    subscribe_track_received = threading.Event()

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

    def collaborator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[RobotDog] on_task_collaboration_request payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.accept_task_collaboration(collaborator_id, task_id, payload["src_agent_id"])
        collaboration_request_received.set()

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

    def collaborator_on_message_received(message_type: str, payload: dict) -> None:
        if message_type == "SUBSCRIBE_TRACK":
            subscribe_track_received.set()

    initiator.register_callbacks(
        on_discover_result_received=initiator_on_discover_result_received,
        on_moq_message_received=lambda namespace, track, payload: on_moq_message_received(
            "AliceAgent", namespace, track, payload
        ),
    )
    collaborator.register_callbacks(
        on_task_collaboration_request=collaborator_on_task_collaboration_request,
        on_task_start_command=collaborator_on_task_start_command,
        on_message_received=collaborator_on_message_received,
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

    print(initiator.request_task_collaboration(initiator_id, task_id, ["声光驱离"]))

    _wait_event(collaboration_request_received, args.wait_timeout, "TASK_REQUEST_COLLABORATION")
    _wait_event(discover_result_received, args.wait_timeout, "DISCOVER_RESULT")
    _wait_event(task_start_received, args.wait_timeout, "START_TASK")
    _wait_event(subscribe_track_received, args.wait_timeout, "SUBSCRIBE_TRACK")

    report_task_info_for_duration(
        initiator,
        initiator_id,
        task_id,
        "Location",
        duration_seconds=args.report_duration,
        start_seq=2,
    )
    collaborator.request_terminate_task(collaborator_id, task_id, "demo finished")
    collaborator.logout_network(collaborator_id)
    initiator.request_terminate_task(initiator_id, task_id, "demo finished")
    initiator.logout_network(initiator_id)
    collaborator.deregister_robot(collaborator_id, "demo completed")
    initiator.deregister_robot(initiator_id, "demo completed")


if __name__ == "__main__":
    main()
