from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import uvicorn

from acn_sdk.utils.logging_config import setup_logging


setup_logging()
logger = logging.getLogger("mock_agent_gw")
app = FastAPI(title="Mock AgentGW", version="0.1.0")


class DebugPushRequest(BaseModel):
    agent_id: str
    message: dict[str, Any]


class DebugTaskRequestCollaborationRequest(BaseModel):
    collaborator_agent_id: str
    initiator_agent_id: str
    task_id: str
    task_description: str
    initiator_skills: list[str]


class DebugDiscoverResultRequest(BaseModel):
    initiator_agent_id: str
    collaborator_ids: list[str]


class DebugStartTaskRequest(BaseModel):
    collaborator_agent_id: str
    initiator_agent_id: str
    task_id: str
    task_description: str


class DebugSubscribeTrackRequest(BaseModel):
    subscriber_agent_id: str
    publisher_agent_id: str
    task_id: str
    topic: str


class ConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def register(self, agent_id: str, websocket: WebSocket) -> None:
        self._connections[agent_id] = websocket
        logger.info("Registered websocket connection for agent_id=%s", agent_id)

    def unregister(self, agent_id: str) -> None:
        if agent_id in self._connections:
            self._connections.pop(agent_id, None)
            logger.info("Unregistered websocket connection for agent_id=%s", agent_id)

    async def send_to(self, agent_id: str, message: dict[str, Any]) -> None:
        websocket = self._connections.get(agent_id)
        if websocket is None:
            raise KeyError(agent_id)
        logger.info("Pushing message to agent_id=%s payload=%s", agent_id, message)
        await websocket.send_json(message)


registry = ConnectionRegistry()


@app.websocket("/ws")
async def websocket_gateway(websocket: WebSocket) -> None:
    await websocket.accept()
    agent_id: str | None = None
    try:
        while True:
            message = await websocket.receive_json()
            logger.info("Received websocket message: %s", message)
            message_type = message.get("type")
            payload = message.get("payload", {})

            if message_type == "SETUP":
                agent_id = payload.get("src_agent_id")
                if not agent_id:
                    await websocket.send_json(_ws_message("SETUP", {"status": "ERROR", "reason": "missing src_agent_id"}))
                    continue
                await registry.register(agent_id, websocket)
                await websocket.send_json(_ws_message("SETUP", {"status": "OK"}))
                continue

            if message_type == "DISCONNECTION":
                if agent_id is not None:
                    registry.unregister(agent_id)
                await websocket.close()
                break

            logger.info("Processed websocket control message type=%s payload=%s", message_type, payload)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for agent_id=%s", agent_id)
    finally:
        if agent_id is not None:
            registry.unregister(agent_id)


@app.post("/debug/ws-message")
async def debug_push_message(payload: DebugPushRequest) -> dict[str, Any]:
    try:
        await registry.send_to(payload.agent_id, payload.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"agent not connected: {payload.agent_id}") from exc
    return {"result": "success", "agent_id": payload.agent_id}


@app.post("/debug/task-request-collaboration")
async def debug_task_request_collaboration(payload: DebugTaskRequestCollaborationRequest) -> dict[str, Any]:
    message = _ws_message(
        "TASK_REQUEST_COLLABORATION",
        {
            "src_agent_id": payload.initiator_agent_id,
            "dst_agent_id": payload.collaborator_agent_id,
            "task_id": payload.task_id,
            "task_description": payload.task_description,
            "agent_card": {
                "agent_id": payload.initiator_agent_id,
                "skill": payload.initiator_skills,
            },
        },
    )
    try:
        await registry.send_to(payload.collaborator_agent_id, message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"agent not connected: {payload.collaborator_agent_id}") from exc
    return {"result": "success", "agent_id": payload.collaborator_agent_id, "task_id": payload.task_id}


@app.post("/debug/discover-result")
async def debug_discover_result(payload: DebugDiscoverResultRequest) -> dict[str, Any]:
    message = _ws_message(
        "DISCOVER_RESULT",
        {
            "src_agent_id": "ARF",
            "dst_agent_id": payload.initiator_agent_id,
            "discover_result": payload.collaborator_ids,
        },
    )
    try:
        await registry.send_to(payload.initiator_agent_id, message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"agent not connected: {payload.initiator_agent_id}") from exc
    return {"result": "success", "agent_id": payload.initiator_agent_id, "discover_result": payload.collaborator_ids}


@app.post("/debug/start-task")
async def debug_start_task(payload: DebugStartTaskRequest) -> dict[str, Any]:
    message = _ws_message(
        "START_TASK",
        {
            "src_agent_id": payload.initiator_agent_id,
            "dst_agent_id": payload.collaborator_agent_id,
            "task_id": payload.task_id,
            "task_description": payload.task_description,
        },
    )
    try:
        await registry.send_to(payload.collaborator_agent_id, message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"agent not connected: {payload.collaborator_agent_id}") from exc
    return {"result": "success", "agent_id": payload.collaborator_agent_id, "task_id": payload.task_id}


@app.post("/debug/subscribe-track")
async def debug_subscribe_track(payload: DebugSubscribeTrackRequest) -> dict[str, Any]:
    message = _ws_message(
        "SUBSCRIBE_TRACK",
        {
            "src_agent_id": payload.publisher_agent_id,
            "task_id": payload.task_id,
            "track_list": [
                {
                    "namespace": f"/{payload.task_id}/{payload.publisher_agent_id}",
                    "track": payload.topic,
                }
            ],
        },
    )
    try:
        await registry.send_to(payload.subscriber_agent_id, message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"agent not connected: {payload.subscriber_agent_id}") from exc
    return {"result": "success", "agent_id": payload.subscriber_agent_id, "task_id": payload.task_id, "topic": payload.topic}


def _ws_message(message_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": message_type,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the mock AgentGW service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9002)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
