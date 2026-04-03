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
        self.capability_names: list[str] = []
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
        capability_names = content.get("capability_names")
        if capability_names is not None:
            self.capability_names = capability_names
        else:
            self.capability_names = []
        capability_vcs = content.get("capability_vcs")
        if capability_vcs is not None:
            self.capability_vcs = capability_vcs
        elif content.get("capability_vc") is not None:
            self.capability_vcs = [content["capability_vc"]]
        else:
            self.capability_vcs = []
        if not self.capability_names:
            self.capability_names = self._extract_capability_names(self.capability_vcs)
        self.robot_name = content.get("robot_name")
        self.owner = content.get("owner")
        self.priority = content.get("priority")
        self.metadata = content.get("metadata", {})
        self._logger.info("Loaded identity state: %s", content)

    def save(self) -> None:
        state = {
            "agent_id": self.agent_id,
            "vc0": self.vc0,
            "capability_names": self.capability_names,
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
        self.capability_vcs.extend(capability_vcs)
        self.capability_names = self._unique_extend(
            self.capability_names,
            self._extract_capability_names(capability_vcs),
        )
        self.save()

    def get_pending_capabilities(self, capability_names: list[str]) -> list[str]:
        known_capabilities = set(self.capability_names)
        pending_capabilities: list[str] = []
        seen_pending: set[str] = set()
        for capability in capability_names:
            if capability in known_capabilities or capability in seen_pending:
                continue
            seen_pending.add(capability)
            pending_capabilities.append(capability)
        return pending_capabilities

    def query_agent_id(self, robot_name: str, owner: str) -> str | None:
        if self.robot_name == robot_name and self.owner == owner:
            return self.agent_id
        return None

    def clear(self) -> None:
        self._logger.info("Clearing identity state.")
        self.agent_id = None
        self.vc0 = None
        self.capability_names = []
        self.capability_vcs = []
        self.robot_name = None
        self.owner = None
        self.priority = None
        self.metadata = {}
        self.save()

    @staticmethod
    def _extract_capability_names(capability_vcs: list[dict[str, Any]]) -> list[str]:
        capability_names: list[str] = []
        for capability_vc in capability_vcs:
            claims = capability_vc.get("claims") if isinstance(capability_vc, dict) else None
            if not isinstance(claims, dict):
                continue
            capability_name = claims.get("agent_attribute")
            if isinstance(capability_name, str):
                capability_names.append(capability_name)
        return capability_names

    @staticmethod
    def _unique_extend(existing: list[str], new_items: list[str]) -> list[str]:
        merged = list(existing)
        for item in new_items:
            if item not in merged:
                merged.append(item)
        return merged
