from __future__ import annotations

import json
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from acn_sdk.config import SDKConfig

DEFAULT_RUNTIME_ROOT = Path(tempfile.gettempdir()) / "acn-sdk-task-demo"
DEFAULT_SESSION_NAME = "demo-task-flow"
DEFAULT_AGENT_GW_BASE_URL = "http://127.0.0.1:9002"
DEFAULT_WAIT_TIMEOUT_SECONDS = 120.0


def prepare_session_dir(runtime_root: Path, session_name: str, reset: bool = False) -> Path:
    session_dir = runtime_root / session_name
    if reset and session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


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


def current_location_bytes(*, seq: int | None = None, reported_at: str | None = None) -> bytes:
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


def post_agent_gw_debug(path: str, payload: dict[str, Any], agent_gw_base_url: str = DEFAULT_AGENT_GW_BASE_URL) -> None:
    with httpx.Client(timeout=5.0, trust_env=False) as client:
        response = client.post(f"{agent_gw_base_url}{path}", json=payload)
    response.raise_for_status()


def push_task_request_collaboration(
    collaborator_agent_id: str,
    initiator_agent_id: str,
    task_id: str,
    task_description: str,
    initiator_skills: list[str],
) -> None:
    post_agent_gw_debug(
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
    post_agent_gw_debug(
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
    post_agent_gw_debug(
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
    post_agent_gw_debug(
        "/debug/subscribe-track",
        {
            "subscriber_agent_id": subscriber_agent_id,
            "publisher_agent_id": publisher_agent_id,
            "task_id": task_id,
            "topic": topic,
        },
    )


def write_runtime_value(session_dir: Path, name: str, value: str) -> Path:
    path = session_dir / name
    path.write_text(value, encoding="utf-8")
    return path


def read_runtime_value(session_dir: Path, name: str) -> str | None:
    path = session_dir / name
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


def wait_for_runtime_value(session_dir: Path, name: str, timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS) -> str:
    deadline = time.monotonic() + timeout_seconds
    path = session_dir / name
    while time.monotonic() < deadline:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {name} in {session_dir}")
