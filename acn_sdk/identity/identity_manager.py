from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


class IdentityManager:
    def __init__(self, identity_file: str) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self.identity_file = Path(identity_file)
        self.identity_file.parent.mkdir(parents=True, exist_ok=True)
        self.agent_id: str | None = None
        self.vc0: dict[str, Any] | None = None
        self.capability_vcs: list[dict[str, Any]] = []
        self.robot_name: str | None = None
        self.owner: str | None = None
        self.priority: int | None = None
        self.metadata: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if not self.identity_file.exists():
            return
        content = json.loads(self.identity_file.read_text(encoding="utf-8"))
        self.agent_id = content.get("agent_id")
        self.vc0 = content.get("vc0")
        capability_vcs = content.get("capability_vcs")
        if capability_vcs is not None:
            self.capability_vcs = capability_vcs
        elif content.get("capability_vc") is not None:
            self.capability_vcs = [content["capability_vc"]]
        else:
            self.capability_vcs = []
        self.robot_name = content.get("robot_name")
        self.owner = content.get("owner")
        self.priority = content.get("priority")
        self.metadata = content.get("metadata", {})
        self._logger.info("Loaded identity state: %s", content)

    def save(self) -> None:
        state = {
            "agent_id": self.agent_id,
            "vc0": self.vc0,
            "capability_vcs": self.capability_vcs,
            "robot_name": self.robot_name,
            "owner": self.owner,
            "priority": self.priority,
            "metadata": self.metadata,
        }
        self.identity_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._logger.info("Persisted identity state: %s", state)

    def set_identity(
        self,
        agent_id: str,
        vc0: dict[str, Any],
        robot_name: str,
        owner: str,
        priority: int,
        metadata: dict[str, Any],
    ) -> None:
        self.agent_id = agent_id
        self.vc0 = vc0
        self.robot_name = robot_name
        self.owner = owner
        self.priority = priority
        self.metadata = metadata
        self.save()

    def set_capability_vcs(self, capability_vcs: list[dict[str, Any]]) -> None:
        self.capability_vcs = capability_vcs
        self.save()

    def query_robot_id(self, robot_name: str, owner: str) -> str | None:
        if self.robot_name == robot_name and self.owner == owner:
            return self.agent_id
        return None

    def clear(self) -> None:
        self._logger.info("Clearing identity state.")
        self.agent_id = None
        self.vc0 = None
        self.capability_vcs = []
        self.robot_name = None
        self.owner = None
        self.priority = None
        self.metadata = {}
        self.save()
