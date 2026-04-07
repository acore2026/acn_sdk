from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, AgentInfo
from demo_task_shared import (
    DEFAULT_RUNTIME_ROOT,
    build_config_from_repo,
    prepare_session_dir,
)

DEFAULT_SESSION_NAME = "demo-task-flow-realtime"


def on_message_received(agent_name: str, namespace: str, track: str, payload: bytes) -> None:
    print(f"[{agent_name}] moq_message namespace={namespace} track={track} payload={payload!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the collaborator side without stubbing intermediate messages.")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--session-name", default=DEFAULT_SESSION_NAME)
    parser.add_argument("--reset", dest="reset", action="store_true", help="Clear prior demo files before starting.")
    parser.add_argument("--no-reset", dest="reset", action="store_false", help="Keep prior demo files.")
    parser.add_argument("--wait-timeout", type=float, default=120.0)
    parser.set_defaults(reset=False)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session_dir = prepare_session_dir(args.runtime_root, args.session_name, reset=args.reset)
    print(f"session_dir={session_dir}")

    collaborator_config = build_config_from_repo(session_dir, identity_name="collaborator")
    collaborator = AcnSDK(
        agent_name="RobotDog",
        config_path=collaborator_config,
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
    if not collaborator_ok:
        raise RuntimeError(collaborator_id)
    print(f"collaborator_id={collaborator_id}")
    print(f"collaborator local agent_info={collaborator.query_agent_info(collaborator_id)}")
    print(f"collaborator owner agents={collaborator.query_agent_list('13800138111')}")

    task_id_holder: dict[str, str] = {"value": ""}

    def collaborator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[RobotDog] on_task_collaboration_request payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.accept_task_collaboration(collaborator_id, task_id)

    def collaborator_on_task_start_command(payload: dict) -> None:
        print(f"[RobotDog] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.request_task_execution(
            collaborator_id,
            payload["task_description"],
            task_id=task_id,
        )

    collaborator.register_callbacks(
        on_task_collaboration_request=collaborator_on_task_collaboration_request,
        on_task_start_command=collaborator_on_task_start_command,
        on_message_received=lambda namespace, track, payload: on_message_received(
            "RobotDog", namespace, track, payload
        ),
    )

    print(collaborator.register_agent_attribute(collaborator_id, ["声光驱离"]))
    print(f"collaborator join={collaborator.join_network(collaborator_id)}")
    time.sleep(args.wait_timeout)

    task_id = task_id_holder["value"]
    if task_id:
        print(collaborator.request_terminate_task(collaborator_id, task_id, "demo finished"))
    print(collaborator.logout_network(collaborator_id))
    print(collaborator.deregister_agent(collaborator_id, "demo completed"))


if __name__ == "__main__":
    main()
