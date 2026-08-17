from __future__ import annotations

import signal
import time

from acn_sdk import AcnSDK, AgentInfo


KEEPALIVE_INTERVAL_SECONDS = 5.0


def main() -> None:
    stop_requested = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    # 1. Initialize RobotDog SDK from acn_sdk/config/config.yaml.
    robotdog = AcnSDK(agent_name="RobotDog")
    print(f"config_path={robotdog.config_path}")
    print(f"identity_file={robotdog.config.storage.identity_file}")

    # 2. Register RobotDog identity.
    robotdog_ok, robotdog_id = robotdog.register_agent_info(
        AgentInfo(
            name="RobotDog",
            owner="13800138111",
            description="RobotDogModel, SN654321",
            priority=4,
            metadata={"region": "CN", "role": "collaborator"},
        )
    )
    if not robotdog_ok:
        raise RuntimeError(robotdog_id)
    print(f"robotdog_id={robotdog_id}")

    task_id_holder: dict[str, str] = {"value": ""}

    # 3. Register task and message callbacks before joining the network.
    def robotdog_on_task_collaboration_request(payload: dict) -> None:
        print(f"[RobotDog] on_task_collaboration_request payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        accept_ok, accept_response = robotdog.accept_task_collaboration(robotdog_id, task_id)
        if not accept_ok:
            raise RuntimeError(accept_response)
        print(f"[RobotDog] accept_task_collaboration result={accept_response}")

    def robotdog_on_discover_result_received(payload: dict) -> None:
        print(f"[RobotDog] on_discover_result_received payload={payload}")
        collaborator_candidates = payload.get("discover_result", [])
        if not collaborator_candidates:
            raise RuntimeError("discover_result is empty")
        task_id = task_id_holder["value"]
        if not task_id:
            raise RuntimeError("task_id is not initialized")
        start_ok, start_response = robotdog.start_task_collaboration(
            robotdog_id,
            collaborator_candidates[0],
            task_id,
            "协同声光驱离",
        )
        if not start_ok:
            raise RuntimeError(start_response)
        print(f"[RobotDog] start_task_collaboration result={start_response}")

    def robotdog_on_task_start_command(payload: dict) -> None:
        print(f"[RobotDog] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        execute_ok, execute_response = robotdog.request_task_execution(
            robotdog_id,
            payload["task_description"],
            task_id=task_id,
        )
        if not execute_ok:
            raise RuntimeError(execute_response)
        print(f"[RobotDog] request_task_execution result={execute_response}")

    def robotdog_on_terminate_task_received(payload: dict) -> None:
        print(f"[RobotDog] on_terminate_task_received payload={payload}")
        task_id = payload.get("task_id")
        reason = payload.get("reason", "")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("task_id is not available in TASK_TERMINATION payload")
        terminate_ok, terminate_response = robotdog.request_terminate_task(robotdog_id, task_id, reason)
        if not terminate_ok:
            raise RuntimeError(terminate_response)
        print(f"[RobotDog] request_terminate_task result={terminate_response}")

    def robotdog_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    callbacks_ok, callbacks_response = robotdog.register_callbacks(
        on_task_collaboration_request=robotdog_on_task_collaboration_request,
        on_discover_result_received=robotdog_on_discover_result_received,
        on_task_start_command=robotdog_on_task_start_command,
        on_terminate_task_received=robotdog_on_terminate_task_received,
        on_message_received=robotdog_on_message_received,
    )
    if not callbacks_ok:
        raise RuntimeError(callbacks_response)

    # 4. Register RobotDog capability.
    capability_ok, capability_response = robotdog.register_agent_attribute(
        robotdog_id,
        ["载重运输", "自主导航", "高清摄像"],
    )
    if not capability_ok:
        raise RuntimeError(capability_response)
    print(f"capability_response={capability_response}")

    # 5. Join network.
    join_ok, join_response = robotdog.join_network(robotdog_id)
    if not join_ok:
        raise RuntimeError(join_response)
    print(f"robotdog join={join_response}")

    print(f"robotdog local agent_info={robotdog.query_agent_info(robotdog_id)}")
    print(f"robotdog owner agents={robotdog.query_agent_list('13800138111')}")
    print("RobotDog is online. Keep this process running to keep websocket connected.")

    while not stop_requested:
        time.sleep(KEEPALIVE_INTERVAL_SECONDS)

    print("Stop requested. Run demo_robotdog_logout_deregister.py to logout and deregister.")


if __name__ == "__main__":
    main()
