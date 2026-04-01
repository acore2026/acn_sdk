from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, RobotInfo
from demo_task_shared import (
    DEFAULT_RUNTIME_ROOT,
    build_config,
    current_location_bytes,
    prepare_session_dir,
    read_runtime_value,
    report_task_info_for_duration,
    wait_for_runtime_value,
    write_runtime_value,
)

DEFAULT_SESSION_NAME = "demo-task-flow-realtime"


def on_moq_message_received(agent_name: str, namespace: str, track: str, payload: bytes) -> None:
    print(f"[{agent_name}] moq_message namespace={namespace} track={track} payload={payload!r}")


def _wait_for_file(session_dir: Path, name: str, timeout_seconds: float) -> str:
    return wait_for_runtime_value(session_dir, name, timeout_seconds=timeout_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the initiator side without stubbing intermediate messages.")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--session-name", default=DEFAULT_SESSION_NAME)
    parser.add_argument("--wait-timeout", type=float, default=120.0)
    parser.add_argument("--report-duration", type=float, default=10.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session_dir = prepare_session_dir(args.runtime_root, args.session_name, reset=False)
    print(f"session_dir={session_dir}")

    initiator_config = build_config(session_dir, identity_name="initiator")
    initiator = AcnSDK(
        robot_name="AliceAgent",
        config_path=initiator_config,
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
    if not initiator_ok:
        raise RuntimeError(initiator_id)
    print(f"initiator_id={initiator_id}")
    write_runtime_value(session_dir, "initiator.agent_id", initiator_id)

    wait_for_runtime_value(session_dir, "collaborator.ready", timeout_seconds=args.wait_timeout)
    collaborator_agent_id = read_runtime_value(session_dir, "collaborator.agent_id")
    if not collaborator_agent_id:
        raise RuntimeError("collaborator.agent_id is missing")
    print(f"collaborator_id={collaborator_agent_id}")

    task_id_holder: dict[str, str] = {"value": ""}

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

    initiator.register_callbacks(
        on_discover_result_received=initiator_on_discover_result_received,
        on_moq_message_received=lambda namespace, track, payload: on_moq_message_received(
            "AliceAgent", namespace, track, payload
        ),
    )

    print(initiator.register_agent_attribute(initiator_id, ["可疑人员识别", "目标跟踪"]))
    print(f"initiator join={initiator.join_network(initiator_id)}")
    write_runtime_value(session_dir, "initiator.ready", initiator_id)

    task_ok, task_id = initiator.request_task_execution(initiator_id, "可疑人员驱离")
    if not task_ok:
        raise RuntimeError(task_id)
    task_id_holder["value"] = task_id
    write_runtime_value(session_dir, "task_id", task_id)
    print(f"task_id={task_id}")
    print(initiator.task_info_report(initiator_id, task_id, "Location", current_location_bytes()))

    print(initiator.request_task_collaboration(initiator_id, task_id, ["声光驱离"]))
    _wait_for_file(session_dir, "collaborator.subscribed", timeout_seconds=args.wait_timeout)

    report_task_info_for_duration(initiator, initiator_id, task_id, "Location", duration_seconds=args.report_duration)

    try:
        print(initiator.request_terminate_task(initiator_id, task_id, "demo finished"))
        print(initiator.logout_network(initiator_id))
        print(initiator.deregister_robot(initiator_id, "demo completed"))
    finally:
        write_runtime_value(session_dir, "shutdown.signal", "done")


if __name__ == "__main__":
    main()
