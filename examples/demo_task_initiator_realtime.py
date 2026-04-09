from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, AgentInfo
from acn_sdk.core.settings import SDKConfig

DEFAULT_RUNTIME_ROOT = Path(tempfile.gettempdir()) / "acn-sdk-task-demo"
DEFAULT_SESSION_NAME = "demo-task-flow-realtime"
REPO_CONFIG_PATH = Path(__file__).resolve().parent.parent / "acn_sdk" / "config" / "config.yaml"
DEFAULT_WAIT_TIMEOUT_SECONDS = 120.0
DEFAULT_SUBSCRIPTION_GRACE_PERIOD_SECONDS = 5.0


# 运行辅助函数。
# 这些函数让 realtime 示例保持自包含，不再依赖 demo_task_shared。
def prepare_session_dir(runtime_root: Path, session_name: str, reset: bool = False) -> Path:
    # 每次 realtime 运行都使用独立的 session 目录，避免不同运行之间的文件冲突。
    session_dir = runtime_root / session_name
    if reset and session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def build_config_from_repo(base_dir: Path, identity_name: str, repo_config_path: Path = REPO_CONFIG_PATH) -> Path:
    # 先读取仓库配置，再把存储路径改到当前 session 目录下。
    config = SDKConfig.load(repo_config_path)
    config.storage.identity_file = str(base_dir / identity_name / "identity.json")
    config.storage.private_key_file = str(base_dir / identity_name / "keys" / "private.pem")
    config.storage.public_key_file = str(base_dir / identity_name / "keys" / "public.pem")
    config.storage.log_dir = str(base_dir / identity_name / "logs")
    config_path = base_dir / identity_name / "config.yaml"
    config.save(config_path)
    return config_path


def current_location_bytes(*, seq: int | None = None, reported_at: str | None = None) -> bytes:
    # 组装演示期间会反复上报的定位遥测数据。
    payload = {
        "longitude": 116.404,
        "latitude": 39.915,
        "altitude": 50.5,
    }
    if seq is not None:
        payload["seq"] = seq
    if reported_at is not None:
        payload["reported_at"] = reported_at
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def report_task_info_for_duration(
    sdk: Any,
    agent_id: str,
    task_id: str,
    topic: str,
    duration_seconds: float,
    interval_seconds: float = 1.0,
    start_seq: int = 1,
) -> None:
    # 在指定时长内持续发送任务遥测数据。
    seq = start_seq
    deadline = time.monotonic() + duration_seconds
    while True:
        reported_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        response = sdk.task_info_report(
            agent_id,
            task_id,
            topic,
            current_location_bytes(seq=seq, reported_at=reported_at),
        )
        print(response)
        seq += 1
        if time.monotonic() >= deadline:
            break
        time.sleep(interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the initiator side without stubbing intermediate messages.")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--session-name", default=DEFAULT_SESSION_NAME)
    parser.add_argument("--wait-timeout", type=float, default=DEFAULT_WAIT_TIMEOUT_SECONDS)
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

    # 第 1 步：在 session 目录中创建 initiator 的运行配置。
    initiator_config = build_config_from_repo(session_dir, identity_name="initiator")
    initiator = AcnSDK(
        agent_name="AliceAgent",
        config_path=initiator_config,
    )

    # 第 2 步：注册 agent，并确认 SDK 返回的身份信息。
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

    # 这个回调在 collaborator 发起协同时触发，用来接收任务请求。
    def initiator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[AliceAgent] on_task_collaboration_request payload={payload}")

    # 这个回调是关键交接点：当发现结果返回后，选出 collaborator 并启动协同任务。
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

    # 这个回调用来记录协同流程中返回的启动命令。
    def initiator_on_task_start_command(payload: dict) -> None:
        print(f"[AliceAgent] on_task_start_command payload={payload}")

    # 打印 MQTT/MoQ 载荷，方便在终端里观察 realtime 数据流。
    def initiator_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    # 第 3 步：注册驱动整个事件序列的回调函数。
    initiator.register_callbacks(
        on_task_collaboration_request=initiator_on_task_collaboration_request,
        on_discover_result_received=initiator_on_discover_result_received,
        on_task_start_command=initiator_on_task_start_command,
        on_message_received=initiator_on_message_received,
    )

    # 第 4 步：上报能力并加入网络，然后再申请任务。
    print(initiator.register_agent_attribute(initiator_id, ["可疑人员识别", "目标跟踪"]))
    print(f"initiator join={initiator.join_network(initiator_id)}")

    # 第 5 步：申请任务，并立刻发送第一条定位样本，让任务一开始就有实时数据。
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

    # 第 6 步：请求协同，并等待 discovery 回调把流程推进到下一阶段。
    print(initiator.request_task_collaboration(initiator_id, task_id, ["声光驱离"]))
    if not discover_result_received.wait(args.wait_timeout):
        raise RuntimeError("Timed out waiting for DISCOVER_RESULT.")
    time.sleep(args.subscription_grace_period)

    # 第 7 步：在 collaborator 活跃期间持续上报遥测数据。
    report_task_info_for_duration(
        initiator,
        initiator_id,
        task_id,
        "Location",
        duration_seconds=args.report_duration,
        start_seq=2,
    )

    # 第 8 步：终止任务、退出网络，并清理 demo 身份信息。
    print(initiator.request_terminate_task(initiator_id, task_id, "demo finished"))
    print(initiator.logout_network(initiator_id))
    print(initiator.deregister_agent(initiator_id, "demo completed"))


if __name__ == "__main__":
    main()
