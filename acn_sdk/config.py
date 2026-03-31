from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class NetworkConfig(BaseModel):
    network_ip: str = "127.0.0.1"
    acn_agent_port: int = 9010
    arf_port: int = 9001
    agent_gw_ws_port: int = 9002
    agent_gw_moq_port: int = 9003
    web_ui_port: int = 9004
    path: str = "/ws"

    @property
    def acn_agent_url(self) -> str:
        return f"http://{self.network_ip}:{self.acn_agent_port}"

    @property
    def arf_url(self) -> str:
        return f"http://{self.network_ip}:{self.arf_port}"

    @property
    def agent_gw_ws_url(self) -> str:
        return f"ws://{self.network_ip}:{self.agent_gw_ws_port}{self.path}"

    @property
    def web_ui_url(self) -> str:
        return f"http://{self.network_ip}:{self.web_ui_port}"


class StorageConfig(BaseModel):
    identity_file: str = "data/identity.json"
    private_key_file: str = "data/keys/private_key.pem"
    public_key_file: str = "data/keys/public_key.pem"
    log_dir: str = "logs"


class SDKConfig(BaseModel):
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    log_level: str = "INFO"

    @classmethod
    def load(cls, path: str | Path) -> "SDKConfig":
        config_path = Path(path).expanduser().resolve()
        with config_path.open("r", encoding="utf-8") as file:
            content = yaml.safe_load(file) or {}
        config = cls.model_validate(content)
        base_dir = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent

        def resolve_path(value: str) -> str:
            candidate = Path(value).expanduser()
            if candidate.is_absolute():
                return str(candidate)
            return str((base_dir / candidate).resolve())

        config.storage.identity_file = resolve_path(config.storage.identity_file)
        config.storage.private_key_file = resolve_path(config.storage.private_key_file)
        config.storage.public_key_file = resolve_path(config.storage.public_key_file)
        config.storage.log_dir = resolve_path(config.storage.log_dir)
        return config

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as file:
            yaml.safe_dump(self.model_dump(mode="json"), file, allow_unicode=True, sort_keys=False)
