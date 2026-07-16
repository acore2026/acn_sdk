from __future__ import annotations

from pathlib import Path
from typing import Any

from acn_gateway.config import GatewaySettings
from acn_gateway.service import GatewayService


class FakeSdk:
    def __init__(self) -> None:
        self.callbacks: dict[str, Any] = {}
        self.calls: list[tuple[Any, ...]] = []

    def register_callbacks(self, **callbacks: Any) -> tuple[bool, str]:
        self.callbacks = callbacks
        return True, "OK"

    def register_agent_info(self, agent_info: Any) -> tuple[bool, str]:
        self.calls.append(("register_agent_info", agent_info.name))
        return True, "did:acn:agent:test"

    def register_agent_attribute(self, agent_id: str, capabilities: list[str]) -> tuple[bool, str]:
        self.calls.append(("register_agent_attribute", agent_id, capabilities))
        return True, "{}"

    def join_network(self, agent_id: str) -> tuple[bool, str]:
        self.calls.append(("join_network", agent_id))
        return True, ""

    def request_task_execution(self, agent_id: str, description: str, task_id: str | None = None) -> tuple[bool, str]:
        task_id = task_id or "task-test"
        self.calls.append(("request_task_execution", agent_id, description, task_id))
        return True, task_id

    def broadcast_terminate_task(
        self,
        agent_id: str,
        task_id: str,
        reason: str,
        force: bool,
    ) -> tuple[bool, str]:
        self.calls.append(("broadcast_terminate_task", agent_id, task_id, reason, force))
        return True, ""

    def request_terminate_task(
        self,
        agent_id: str,
        task_id: str,
        reason: str,
        force: bool,
    ) -> tuple[bool, str]:
        self.calls.append(("request_terminate_task", agent_id, task_id, reason, force))
        return True, "{}"

    def logout_network(self, agent_id: str) -> tuple[bool, str]:
        self.calls.append(("logout_network", agent_id))
        return True, ""

    def deregister_agent(self, agent_id: str, reason: str) -> tuple[bool, str]:
        self.calls.append(("deregister_agent", agent_id, reason))
        return True, "{}"

    def accept_task_collaboration(self, agent_id: str, task_id: str) -> tuple[bool, str]:
        self.calls.append(("accept_task_collaboration", agent_id, task_id))
        return True, task_id

    def start_task_collaboration(
        self,
        agent_id: str,
        destination: str,
        task_id: str,
        description: str,
    ) -> tuple[bool, str]:
        self.calls.append(("start_task_collaboration", agent_id, destination, task_id, description))
        return True, task_id

    def disconnect_all(self, **_: Any) -> tuple[bool, str]:
        self.calls.append(("disconnect_all",))
        return True, "offline"


def settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings.model_validate(
        {
            "python_sdk": {
                "source_path": "/unused",
                "runtime_dir": str(tmp_path),
            },
            "agent": {
                "name": "TestAgent",
                "owner": "+8613800138000",
                "description": "test",
            },
            "capabilities": ["cap-a", "cap-b"],
            "task": {
                "description": "configured task",
                "termination_reason": "configured end",
            },
            "callbacks": {"fetch_tracks": ["Location"]},
        }
    )


def test_seven_trigger_operations_and_termination_callback(tmp_path: Path) -> None:
    fake = FakeSdk()
    service = GatewayService(settings(tmp_path), sdk_factory=lambda _: fake)
    service.start()

    assert service.register_identity().data["agent_id"] == "did:acn:agent:test"
    assert service.register_capabilities().result
    assert service.join_network().result
    assert service.execute_task().data["task_id"] == "task-test"
    assert service.broadcast_terminate_task().result

    blocked_logout = service.logout_network()
    assert not blocked_logout.result
    assert "termination" in blocked_logout.message

    fake.callbacks["on_terminate_task_received"](
        {"task_id": "task-test", "reason": "broadcast received"}
    )
    assert service.state()["task_status"] == "terminated"
    assert service.logout_network().result
    assert service.deregister().result
    assert service.state()["agent_id"] is None


def test_callbacks_are_kept_inside_gateway(tmp_path: Path) -> None:
    fake = FakeSdk()
    service = GatewayService(settings(tmp_path), sdk_factory=lambda _: fake)
    service.start()
    service.register_identity()
    service.join_network()

    fake.callbacks["on_task_collaboration_request"]({"task_id": "task-collab"})
    fake.callbacks["on_discover_result_received"](
        {"task_id": "task-collab", "discover_result": ["did:acn:agent:peer"]}
    )
    modes = fake.callbacks["on_subscribe_track_received"](
        {
            "track_list": [
                {"namespace": "/task/agent", "track": "Location"},
                {"namespace": "/task/agent", "track": "Status"},
            ]
        }
    )
    fake.callbacks["on_message_received"]("/task/agent", "Status", b"payload")

    assert ("accept_task_collaboration", "did:acn:agent:test", "task-collab") in fake.calls
    assert any(call[0] == "start_task_collaboration" for call in fake.calls)
    assert modes == {
        "/task/agent::Location": "fetch",
        "/task/agent::Status": "subscribe",
    }
    assert service.state()["moq_messages_received"] == 1
