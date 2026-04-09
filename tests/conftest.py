from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from acn_sdk.core.settings import SDKConfig
import acn_sdk.sdk as sdk_module
from acn_sdk.network.http_client import HttpClient


class MockPipelineLogReporter:
    def __init__(self, web_ui_url: str, session: object | None = None) -> None:
        self.web_ui_url = web_ui_url
        self.session = session
        self.records: list[dict[str, Any]] = []

    def report(self, **payload: Any) -> None:
        self.records.append(payload)

    def close(self) -> None:
        return None


class MockResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class MockHttpSession:
    def __init__(self, name: str) -> None:
        self.name = name
        self.requests: list[tuple[str, dict[str, Any], dict[str, str] | None]] = []

    def post(self, url: str, json: dict[str, Any], headers: dict[str, str] | None = None) -> MockResponse:
        self.requests.append((url, json, headers))
        if url == "/idm/v1/identity-applications":
            now = datetime.now(timezone.utc)
            payload = {
                "result": "success",
                "agent_id": f"did:acn:agent:{uuid4()}",
                "vc0": {
                    "context": ["3gpp-ts-33.xxx-v20.0.0"],
                    "id": f"CMCC/credentials/{secrets.randbelow(10000):04d}",
                    "type": ["VerifiableCredential", "BindingSIMCredential"],
                    "issuer": "did:udid:NewTypeOperator.rid678@6gc.mnc015.mcc234.3gppnetwork",
                    "valid_from": now.isoformat(),
                    "valid_until": (now + timedelta(days=365)).isoformat(),
                    "claims": {
                        "agent_name": json["name"],
                        "agent_id": f"did:acn:agent:{uuid4()}",
                        "agent_attribute": "运营商颁发，Agent与主UE的绑定关系，用于对外出示，审计确权",
                        "master_id": "type0.master.mock@3gppnetwork.org",
                        "self_id": "type0.self.mock@3gppnetwork.org",
                    },
                    "proof": {
                        "creator": "did:udid:NewTypeOperator.rid678@6gc.mnc015.mcc234.3gppnetwork#keys-1",
                        "signature_value": "mock-proof-signature",
                    },
                },
            }
            return MockResponse(200, payload)

        if url == "/arf/v1/agent-cards":
            capabilities = [
                vc["claims"]["agent_attribute"]
                for vc in json["vc_list"][1:]
                if "claims" in vc and "agent_attribute" in vc["claims"]
            ]
            payload = {
                "result": "success",
                "message": "Agent capability registered",
                "agent_id": json["agent_id"],
                "capabilities": capabilities,
            }
            return MockResponse(200, payload)

        if url == "/acn-agent/v1/agent-deletions":
            payload = {
                "result": "success",
                "message": "Agent deleted",
                "agent_id": json["agent_id"],
                "reason": json["reason"],
            }
            return MockResponse(200, payload)

        if url == "/acn-agent/v1/task-executions":
            payload = {
                "result": "success",
                "message": "Task execution requested",
                "agent_id": json["agent_id"],
                "task_id": json["task_id"],
                "description": json["description"],
            }
            return MockResponse(200, payload)

        if url == "/acn-agent/v1/task-execution-terminations":
            payload = {
                "result": "success",
                "message": "Task termination requested",
                "agent_id": json["agent_id"],
                "task_id": json["task_id"],
                "reason": json["reason"],
                "force": json["force"],
            }
            return MockResponse(200, payload)

        if url == "/arf/v1/agent-discoveries":
            payload = {
                "result": "success",
                "message": "Agent discovery requested",
                "agent_id": json["agent_id"],
                "task_id": json["task_id"],
                "required_capabilities": json["required_capabilities"],
            }
            return MockResponse(200, payload)

        if url == "/arf/v1/agent-info":
            payload = {
                "agent_id": json["agent_id"],
                "agent_name": "巡检机器人A",
                "agent_status": "online",
                "agent_capabilities": ["camera", "monitoring", "night_vision"],
                "priority": 1,
            }
            return MockResponse(200, payload)

        if url == "/acn-agent/v1/owner-agents":
            payload = [
                {
                    "agent_id": "did:acn:agent:111111",
                    "agent_name": "巡检机器人A",
                    "agent_status": "online",
                    "agent_capabilities": ["camera", "monitoring", "night_vision"],
                    "priority": 1,
                },
                {
                    "agent_id": "did:acn:agent:222222",
                    "agent_name": "巡检机器人B",
                    "agent_status": "offline",
                    "agent_capabilities": ["speaker"],
                    "priority": 2,
                },
            ]
            return MockResponse(200, payload)

        return MockResponse(404, {"result": "error", "message": "unknown path"})

    def close(self) -> None:
        return None


@pytest.fixture()
def sdk_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SDKConfig:
    config = SDKConfig.model_validate(
        {
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
                "identity_file": str(tmp_path / "identity.json"),
                "private_key_file": str(tmp_path / "keys" / "private.pem"),
                "public_key_file": str(tmp_path / "keys" / "public.pem"),
                "log_dir": str(tmp_path / "logs"),
            },
            "log_level": "INFO",
        }
    )
    config_path = tmp_path / "config.yaml"
    config.save(config_path)
    monkeypatch.setattr(sdk_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        HttpClient,
        "__init__",
        _build_http_client_init(MockHttpSession("acn_agent"), MockHttpSession("arf")),
        raising=False,
    )
    monkeypatch.setattr(sdk_module, "PipelineLogReporter", MockPipelineLogReporter)
    return config


def _build_http_client_init(acn_session: MockHttpSession, arf_session: MockHttpSession) -> Any:
    def _init(
        self: HttpClient,
        base_url: str,
        arf_base_url: str | None = None,
        session_override: object | None = None,
        arf_session_override: object | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.arf_base_url = (arf_base_url or base_url).rstrip("/")
        import logging

        self._logger = logging.getLogger(self.__class__.__name__)
        self._session = acn_session
        self._arf_session = arf_session

    return _init
