from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import GatewaySettings
from .service import GatewayService, SdkFactory, ServiceResult


class GatewayResponse(BaseModel):
    result: bool
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)


def default_config_path() -> Path:
    configured = os.environ.get("ACN_GATEWAY_CONFIG")
    if configured:
        return Path(configured)
    gateway_dir = Path(__file__).resolve().parents[1]
    local_config = gateway_dir / "config.yaml"
    return local_config if local_config.exists() else gateway_dir / "config.example.yaml"


def create_app(
    config_path: str | Path | None = None,
    *,
    sdk_factory: SdkFactory | None = None,
) -> FastAPI:
    settings = GatewaySettings.load(config_path or default_config_path())
    service = GatewayService(settings, sdk_factory=sdk_factory)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        service.start()
        try:
            yield
        finally:
            service.stop()

    app = FastAPI(title="ACN Android Trigger Gateway", version="0.1.0", lifespan=lifespan)
    app.state.gateway_service = service
    prefix = settings.server.api_prefix

    def response(result: ServiceResult) -> GatewayResponse:
        return GatewayResponse(
            result=result.result,
            message=result.message,
            data=result.data,
            state=service.state(),
        )

    @app.get("/health", response_model=GatewayResponse)
    def health() -> GatewayResponse:
        return GatewayResponse(result=True, data={"service": "acn-gateway"}, state=service.state())

    @app.get(f"{prefix}/status", response_model=GatewayResponse)
    def status() -> GatewayResponse:
        return GatewayResponse(result=True, state=service.state())

    @app.post(f"{prefix}/register-identity", response_model=GatewayResponse)
    def register_identity() -> GatewayResponse:
        return response(service.register_identity())

    @app.post(f"{prefix}/register-capabilities", response_model=GatewayResponse)
    def register_capabilities() -> GatewayResponse:
        return response(service.register_capabilities())

    @app.post(f"{prefix}/join-network", response_model=GatewayResponse)
    def join_network() -> GatewayResponse:
        return response(service.join_network())

    @app.post(f"{prefix}/execute-task", response_model=GatewayResponse)
    def execute_task() -> GatewayResponse:
        return response(service.execute_task())

    @app.post(f"{prefix}/broadcast-terminate-task", response_model=GatewayResponse)
    def broadcast_terminate_task() -> GatewayResponse:
        return response(service.broadcast_terminate_task())

    @app.post(f"{prefix}/logout-network", response_model=GatewayResponse)
    def logout_network() -> GatewayResponse:
        return response(service.logout_network())

    @app.post(f"{prefix}/deregister", response_model=GatewayResponse)
    def deregister() -> GatewayResponse:
        return response(service.deregister())

    return app
