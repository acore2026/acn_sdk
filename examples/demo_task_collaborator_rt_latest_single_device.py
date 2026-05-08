from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, AgentInfo
from acn_sdk.core.settings import SDKConfig

DEFAULT_RUNTIME_ROOT = Path(tempfile.gettempdir()) / "acn-sdk-task-demo"
DEFAULT_SESSION_NAME = "demo-task-rt-latest-single-device"
REPO_CONFIG_PATH = SCRIPT_DIR.parent / "acn_sdk" / "config" / "config.yaml"
DEFAULT_WAIT_TIMEOUT_SECONDS = 90.0
TOPIC_LOCATION = "Location"


def prepare_session_dir(runtime_root: Path, session_name: str, reset: bool = False) -> Path:
    session_dir = runtime_root / session_name
    if reset and session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def build_config_from_repo(base_dir: Path, identity_name: str, repo_config_path: Path = REPO_CONFIG_PATH) -> Path:
    config = SDKConfig.load(repo_config_path)
    config.storage.identity_file = str(base_dir / identity_name / "identity.json")
    config.storage.private_key_file = str(base_dir / identity_name / "keys" / "private.pem")
    config.storage.public_key_file = str(base_dir / identity_name / "keys" / "public.pem")
    config.storage.log_dir = str(base_dir / identity_name / "logs")
    config_path = base_dir / identity_name / "config.yaml"
    config.save(config_path)
    return config_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the rt_latest collaborator side on a single device.")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--session-name", default=DEFAULT_SESSION_NAME)
    parser.add_argument("--reset", action="store_true", help="Clear prior single-device demo files before starting.")
    parser.add_argument("--wait-timeout", type=float, default=DEFAULT_WAIT_TIMEOUT_SECONDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session_dir = prepare_session_dir(args.runtime_root, args.session_name, reset=args.reset)
    collaborator_config = build_config_from_repo(session_dir, identity_name="collaborator")
    print(f"session_dir={session_dir}")
    print(f"collaborator_config={collaborator_config}")

    # 1. 初始化机器狗SDK
    collaborator = AcnSDK(
        agent_name="RobotDog",
        config_path=collaborator_config,
    )

    # 2. 申请 collaborator 数字身份，并确认本地 agent 信息可用（查询非必须）
    collaborator_ok, collaborator_id = collaborator.register_agent_info(
        AgentInfo(
            name="RobotDog",
            owner="13800138111",
            description="RobotDogModel, SN654321",
            priority=4,
            metadata={"region": "CN", "role": "collaborator", "demo": "rt_latest_single_device"},
        )
    )
    if not collaborator_ok:
        raise RuntimeError(collaborator_id)
    print(f"collaborator_id={collaborator_id}")
    print(f"collaborator local agent_info={collaborator.query_agent_info(collaborator_id)}")
    print(f"collaborator owner agents={collaborator.query_agent_list('13800138111')}")

    task_id_holder: dict[str, str] = {"value": ""}

    # 3. 注册回调
    def collaborator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[RobotDog] on_task_collaboration_request payload={payload}")
        task_id = payload.get("task_id")
        if isinstance(task_id, str) and task_id:
            task_id_holder["value"] = task_id
            print(collaborator.accept_task_collaboration(collaborator_id, task_id))

    def collaborator_on_discover_result_received(payload: dict) -> None:
        print(f"[RobotDog] on_discover_result_received payload={payload}")
        collaborator_candidates = payload.get("discover_result", [])
        if not collaborator_candidates:
            raise RuntimeError("discover_result is empty")
        task_id = task_id_holder["value"]
        if not task_id:
            raise RuntimeError("task_id is not initialized")
        result = collaborator.start_task_collaboration(
            collaborator_id,
            collaborator_candidates[0],
            task_id,
            "协同声光驱离",
        )
        print(f"[RobotDog] start_task_collaboration result={result}")

    def collaborator_on_task_start_command(payload: dict) -> None:
        print(f"[RobotDog] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        print(
            collaborator.request_task_execution(
                collaborator_id,
                payload["task_description"],
                task_id=task_id,
            )
        )

    def collaborator_on_terminate_task_received(payload: dict) -> None:
        print(f"[RobotDog] on_terminate_task_received payload={payload}")
        task_id = payload.get("task_id")
        reason = payload.get("reason", "")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("task_id is not available in TASK_TERMINATION payload")
        result = collaborator.request_terminate_task(collaborator_id, task_id, reason)
        print(f"[RobotDog] request_terminate_task result={result}")

    def collaborator_on_subscribe_track_received(payload: dict) -> dict[str, str]:
        print(f"[RobotDog] on_subscribe_track_received payload={payload}")
        track_modes: dict[str, str] = {}
        for track_info in payload.get("track_list", []):
            namespace = track_info.get("namespace")
            track = track_info.get("track")
            if not isinstance(namespace, str) or not isinstance(track, str):
                continue
            mode = "fetch" if track == TOPIC_LOCATION else "subscribe"
            track_modes[f"{namespace}::{track}"] = mode
        print(f"[RobotDog] subscribe track modes={track_modes}")
        return track_modes

    def collaborator_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    print(
        collaborator.register_callbacks(
            on_task_collaboration_request=collaborator_on_task_collaboration_request,
            on_discover_result_received=collaborator_on_discover_result_received,
            on_task_start_command=collaborator_on_task_start_command,
            on_terminate_task_received=collaborator_on_terminate_task_received,
            on_subscribe_track_received=collaborator_on_subscribe_track_received,
            on_message_received=collaborator_on_message_received,
        )
    )

    # 4. 能力注册
    print(collaborator.register_agent_attribute(collaborator_id, ["声光驱离"]))

    # 5. 入网认证
    print(f"collaborator join={collaborator.join_network(collaborator_id)}")

    # 6. 等待无人机发起协作任务，并在固定等待时间后结束 demo
    time.sleep(args.wait_timeout)

    # 7. 终止任务：单独停止任务示例保留为注释；双脚本 demo 默认由 initiator 广播停止
    # task_id = task_id_holder["value"]
    # if task_id:
    #     print(collaborator.request_terminate_task(collaborator_id, task_id, "demo finished"))

    # 8. 退出网络
    print(collaborator.logout_network(collaborator_id))

    # 9. 去注册
    print(collaborator.deregister_agent(collaborator_id, "demo completed"))


if __name__ == "__main__":
    main()
