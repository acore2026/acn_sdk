from __future__ import annotations

import json
from pathlib import Path

from acn_sdk import AcnSDK
from acn_sdk.core.common import NETWORK_ONLINE
from acn_sdk.core.settings import SDKConfig
from acn_sdk.sdk import DEFAULT_CONFIG_PATH


def main() -> None:
    # 1. Read identity.json before SDK initialization.
    config = SDKConfig.load(DEFAULT_CONFIG_PATH)
    identity_file = Path(config.storage.identity_file)
    if not identity_file.exists():
        raise RuntimeError("Please run demo_robotdog_register_join.py first.")
    identity_state = json.loads(identity_file.read_text(encoding="utf-8"))

    # 2. Initialize RobotDog SDK from acn_sdk/config/config.yaml.
    robotdog = AcnSDK(agent_name="RobotDog")
    print(f"config_path={robotdog.config_path}")
    print(f"identity_file={robotdog.config.storage.identity_file}")

    # 3. Restore identity state after SDK initialization.
    robotdog.identity_manager.agent_id = identity_state.get("agent_id")
    robotdog.identity_manager.vc0 = identity_state.get("vc0")
    robotdog.identity_manager.capability_names = identity_state.get("capability_names") or []
    robotdog.identity_manager.capability_vcs = identity_state.get("capability_vcs") or []
    robotdog.identity_manager.agent_name = identity_state.get("agent_name")
    robotdog.identity_manager.owner = identity_state.get("owner")
    robotdog.identity_manager.priority = identity_state.get("priority")
    robotdog.identity_manager.metadata = identity_state.get("metadata") or {}
    robotdog.identity_manager.save()

    robotdog_id = robotdog.identity_manager.agent_id
    if not robotdog_id:
        raise RuntimeError("RobotDog identity state does not contain agent_id.")
    print(f"robotdog_id={robotdog_id}")

    # 4. Reconnect first if this process is not online.
    status_ok, status = robotdog.query_network_status(robotdog_id)
    if not status_ok or status != NETWORK_ONLINE:
        print("RobotDog is not online in this process; reconnecting before logout.")
        join_ok, join_response = robotdog.join_network(robotdog_id)
        if not join_ok:
            raise RuntimeError(join_response)

    # 5. Logout network.
    logout_ok, logout_response = robotdog.logout_network(robotdog_id)
    if not logout_ok:
        raise RuntimeError(logout_response)
    print(f"robotdog logout={logout_response}")

    # 6. Deregister identity.
    deregister_ok, deregister_response = robotdog.deregister_agent(robotdog_id, "demo completed")
    if not deregister_ok:
        raise RuntimeError(deregister_response)
    print(f"deregister_response={deregister_response}")


if __name__ == "__main__":
    main()
