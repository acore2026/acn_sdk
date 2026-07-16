from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=9011, ge=1, le=65535)
    api_prefix: str = "/sdk"

    @field_validator("api_prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        value = "/" + value.strip("/")
        return "" if value == "/" else value


class NetworkSettings(BaseModel):
    network_ip: str = "127.0.0.1"
    acn_agent_port: int = 9010
    arf_port: int = 9001
    agent_gw_ws_port: int = 9002
    agent_gw_moq_port: int = 9003
    web_ui_port: int = 9005
    path: str = "/ws"


class PythonSdkSettings(BaseModel):
    source_path: str = "/home/acn/zxy/td_tech/acn_sdk"
    runtime_dir: str = "./runtime"
    log_level: str = "INFO"
    network: NetworkSettings = Field(default_factory=NetworkSettings)


class AgentSettings(BaseModel):
    name: str
    owner: str = Field(pattern=r"^\+?[0-9]{6,20}$")
    description: str
    priority: int = Field(default=1, ge=0, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskSettings(BaseModel):
    description: str
    termination_reason: str = "Android triggered task termination"
    termination_force: bool = False
    collaboration_description: str = "Gateway automatic collaboration"


class DeregisterSettings(BaseModel):
    reason: str = "Android triggered deregistration"


class CallbackSettings(BaseModel):
    discovery_selection: Literal["first"] = "first"
    fetch_tracks: list[str] = Field(default_factory=list)
    moq_message_policy: Literal["log", "discard"] = "log"


class GatewaySettings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    python_sdk: PythonSdkSettings = Field(default_factory=PythonSdkSettings)
    agent: AgentSettings
    capabilities: list[str]
    task: TaskSettings
    deregister: DeregisterSettings = Field(default_factory=DeregisterSettings)
    callbacks: CallbackSettings = Field(default_factory=CallbackSettings)
    config_path: Path | None = Field(default=None, exclude=True)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if not normalized:
            raise ValueError("capabilities must contain at least one value")
        return normalized

    @classmethod
    def load(cls, path: str | Path) -> "GatewaySettings":
        config_path = Path(path).expanduser().resolve()
        with config_path.open("r", encoding="utf-8") as stream:
            settings = cls.model_validate(yaml.safe_load(stream) or {})
        settings.config_path = config_path
        settings.python_sdk.source_path = settings.resolve_path(settings.python_sdk.source_path)
        settings.python_sdk.runtime_dir = settings.resolve_path(settings.python_sdk.runtime_dir)
        return settings

    def resolve_path(self, value: str) -> str:
        path = Path(value).expanduser()
        if path.is_absolute():
            return str(path.resolve())
        base_dir = self.config_path.parent if self.config_path else Path.cwd()
        return str((base_dir / path).resolve())

    def write_python_sdk_config(self) -> Path:
        runtime_dir = Path(self.python_sdk.runtime_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        config_path = runtime_dir / "sdk-config.yaml"
        content = {
            "network": self.python_sdk.network.model_dump(mode="json"),
            "storage": {
                "identity_file": str(runtime_dir / "data" / "identity.json"),
                "private_key_file": str(runtime_dir / "data" / "keys" / "private_key.pem"),
                "public_key_file": str(runtime_dir / "data" / "keys" / "public_key.pem"),
                "log_dir": str(runtime_dir / "logs"),
            },
            "log_level": self.python_sdk.log_level,
        }
        with config_path.open("w", encoding="utf-8") as stream:
            yaml.safe_dump(content, stream, allow_unicode=True, sort_keys=False)
        return config_path
