from __future__ import annotations

import argparse
import json
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, AgentInfo
from demo_task_shared import (
    DEFAULT_RUNTIME_ROOT,
    build_config_from_repo,
    current_location_bytes,
    prepare_session_dir,
    report_task_info_for_duration,
)

DEFAULT_SESSION_NAME = "demo-task-flow-realtime"
DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS = 5.0

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the initiator side without stubbing intermediate messages.")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--session-name", default=DEFAULT_SESSION_NAME)
    parser.add_argument("--wait-timeout", type=float, default=120.0)
    parser.add_argument(
        "--subscription-grace-period",
        type=float,
        default=DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS,
        help="Seconds to wait after collaboration is accepted before sending sustained task reports.",
    )
    parser.add_argument("--report-duration", type=float, default=10.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session_dir = prepare_session_dir(args.runtime_root, args.session_name, reset=False)
    print(f"session_dir={session_dir}")

    initiator_config = build_config_from_repo(session_dir, identity_name="initiator")
    initiator = AcnSDK(
        agent_name="AliceAgent",
        config_path=initiator_config,
    )

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

    print(initiator.register_agent_attribute(initiator_id, ["可疑人员识别", "目标跟踪"]))
    print(f"initiator join={initiator.join_network(initiator_id)}")

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
    if not discover_result_received.wait(args.wait_timeout):
        raise RuntimeError("Timed out waiting for DISCOVER_RESULT.")
    time.sleep(args.subscription_grace_period)

    report_task_info_for_duration(
        initiator,
        initiator_id,
        task_id,
        "Location",
        duration_seconds=args.report_duration,
        start_seq=2,
    )

    print(initiator.request_terminate_task(initiator_id, task_id, "demo finished"))
    print(initiator.logout_network(initiator_id))
    print(initiator.deregister_agent(initiator_id, "demo completed"))


if __name__ == "__main__":
    main()
