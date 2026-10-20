from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from test_service import FakeSdk, settings

from acn_gateway.service import GatewayService


class StatefulFakeSdk(FakeSdk):
    """FakeSdk that also models the real AcnSDK's identity/network attributes.

    The real AcnSDK exposes ``identity_manager`` (with ``agent_id``) and
    ``network_status``; the environment "Clear" (WS CLEAR message) wipes the
    former and forces the latter to "offline" without notifying the gateway
    wrapper.
    """

    def __init__(self) -> None:
        super().__init__()
        self.identity_manager = SimpleNamespace(agent_id=None)
        self.network_status = "offline"
        self._registrations = 0

    def register_agent_info(self, agent_info: Any) -> tuple[bool, str]:
        self._registrations += 1
        agent_id = f"did:acn:agent:test-{self._registrations}"
        self.calls.append(("register_agent_info", agent_info.name))
        self.identity_manager.agent_id = agent_id
        return True, agent_id

    def join_network(self, agent_id: str) -> tuple[bool, str]:
        result = super().join_network(agent_id)
        self.network_status = "online"
        return result

    def logout_network(self, agent_id: str) -> tuple[bool, str]:
        result = super().logout_network(agent_id)
        self.network_status = "offline"
        return result

    def simulate_environment_clear(self) -> None:
        """What ACF /clear does to a connected agent's SDK state."""
        self.identity_manager.agent_id = None
        self.network_status = "offline"


def test_environment_clear_resets_wrapper_and_allows_reregistration(tmp_path: Path) -> None:
    fake = StatefulFakeSdk()
    service = GatewayService(settings(tmp_path), sdk_factory=lambda _: fake)
    service.start()

    assert service.register_identity().data["agent_id"] == "did:acn:agent:test-1"
    assert service.register_capabilities().result
    assert service.join_network().result
    assert service.execute_task().result

    # Environment reset while the agent is online with a processing task:
    # the SDK wipes its identity, the wrapper still mirrors the old snapshot.
    fake.simulate_environment_clear()

    state = service.state()
    assert state["agent_id"] is None
    assert state["identity_registered"] is False
    assert state["capabilities_registered"] is False
    assert state["network_status"] == "offline"
    assert state["task_status"] == "idle"
    assert state["current_task_id"] is None

    # The app can register again and the full leave/deregister chain works.
    assert service.register_identity().data["agent_id"] == "did:acn:agent:test-2"
    assert service.register_capabilities().result
    assert service.join_network().result
    assert service.execute_task().result
    assert service.broadcast_terminate_task().result
    fake.callbacks["on_terminate_task_received"]({"task_id": "task-fixed", "reason": "done"})
    assert service.logout_network().result
    assert service.deregister().result
    assert service.state()["agent_id"] is None


def test_operations_after_clear_report_register_identity_first(tmp_path: Path) -> None:
    fake = StatefulFakeSdk()
    service = GatewayService(settings(tmp_path), sdk_factory=lambda _: fake)
    service.start()
    service.register_identity()
    service.join_network()
    service.execute_task()

    fake.simulate_environment_clear()

    # Before the fix these returned the SDK's cryptic
    # "The supplied agent_id does not match this device." (terminate) or
    # "Wait for task termination before deregistration" (deregister, blocked
    # by a stale task_status).
    terminate = service.broadcast_terminate_task()
    assert not terminate.result
    assert terminate.message == "Register identity first"

    deregister_result = service.deregister()
    assert not deregister_result.result
    assert deregister_result.message == "Register identity first"


def test_stale_online_flag_follows_sdk_offline(tmp_path: Path) -> None:
    fake = StatefulFakeSdk()
    service = GatewayService(settings(tmp_path), sdk_factory=lambda _: fake)
    service.start()
    service.register_identity()
    service.join_network()
    assert service.state()["network_status"] == "online"

    # WS dropped without an identity wipe: the SDK goes offline, the wrapper
    # should not keep claiming "online" (join must become possible again).
    fake.network_status = "offline"
    assert service.state()["network_status"] == "offline"
    assert service.join_network().result
