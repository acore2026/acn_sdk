from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from acn_sdk import AcnSDK, AgentInfo
from acn_sdk.config import SDKConfig

DEFAULT_RUNTIME_ROOT = Path(tempfile.gettempdir()) / "acn-sdk-task-demo"
DEFAULT_SESSION_NAME = "demo-task-flow-realtime"
REPO_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


# 运行辅助函数。
# 这些函数让 collaborator 示例保持自包含，并把初始化步骤写清楚。
def prepare_session_dir(runtime_root: Path, session_name: str, reset: bool = False) -> Path:
    # 每次运行都隔离开，避免 collaborator 复用上一次留下的旧状态。
    session_dir = runtime_root / session_name
    if reset and session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def build_config_from_repo(base_dir: Path, identity_name: str, repo_config_path: Path = REPO_CONFIG_PATH) -> Path:
    # 复用仓库配置，但把所有运行文件重定向到当前 session。
    config = SDKConfig.load(repo_config_path)
    config.storage.identity_file = str(base_dir / identity_name / "identity.json")
    config.storage.private_key_file = str(base_dir / identity_name / "keys" / "private.pem")
    config.storage.public_key_file = str(base_dir / identity_name / "keys" / "public.pem")
    config.storage.log_dir = str(base_dir / identity_name / "logs")
    config_path = base_dir / identity_name / "config.yaml"
    config.save(config_path)
    return config_path


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

    # 第 1 步：在共享 session 目录中创建 collaborator 的运行配置。
    collaborator_config = build_config_from_repo(session_dir, identity_name="collaborator")
    collaborator = AcnSDK(
        agent_name="RobotDog",
        config_path=collaborator_config,
    )

    # 第 2 步：注册 collaborator，方便 initiator 后续发现它。
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

    # collaborator 保存最新的 task_id，方便后面收到启动/终止消息时响应。
    task_id_holder: dict[str, str] = {"value": ""}

    # initiator 先发起协同请求，这个回调用来确认并接受请求。
    def collaborator_on_task_collaboration_request(payload: dict) -> None:
        print(f"[RobotDog] on_task_collaboration_request payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.accept_task_collaboration(collaborator_id, task_id)

    # 这里打印 discovery 结果，方便查看 initiator 收到了哪些协同候选项。
    def collaborator_on_discover_result_received(payload: dict) -> None:
        print(f"[RobotDog] on_discover_result_received payload={payload}")

    # 当 initiator 发出启动命令时，这个回调把协同流程切换到真正执行任务。
    def collaborator_on_task_start_command(payload: dict) -> None:
        print(f"[RobotDog] on_task_start_command payload={payload}")
        task_id = payload["task_id"]
        task_id_holder["value"] = task_id
        collaborator.request_task_execution(
            collaborator_id,
            payload["task_description"],
            task_id=task_id,
        )

    def collaborator_on_message_received(namespace: str, track: str, payload: bytes) -> None:
        print(f"moq_message namespace={namespace} track={track} payload={payload!r}")

    # 第 3 步：注册回调，定义 collaborator 对不同消息的响应方式。
    collaborator.register_callbacks(
        on_task_collaboration_request=collaborator_on_task_collaboration_request,
        on_discover_result_received=collaborator_on_discover_result_received,
        on_task_start_command=collaborator_on_task_start_command,
        on_message_received=collaborator_on_message_received,
    )

    # 第 4 步：发布能力信息并加入网络，然后等待外部任务进入。
    print(collaborator.register_agent_attribute(collaborator_id, ["声光驱离"]))
    print(f"collaborator join={collaborator.join_network(collaborator_id)}")
    time.sleep(args.wait_timeout)

    # 第 5 步：等待窗口结束后，终止可能还在运行的任务，并移除 demo 中的 agent。
    task_id = task_id_holder["value"]
    if task_id:
        print(collaborator.request_terminate_task(collaborator_id, task_id, "demo finished"))
    print(collaborator.logout_network(collaborator_id))
    print(collaborator.deregister_agent(collaborator_id, "demo completed"))


if __name__ == "__main__":
    main()
