from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import WebSocketMessage

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
NETWORK_ONLINE = "online"
NETWORK_OFFLINE = "offline"
TASK_PROCESSING = "Processing"
TASK_TERMINATED = "Terminated"


class SDKUtilsMixin:
    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _require_local_agent(self, agent_id: str) -> None:
        if not agent_id:
            raise ValueError("agent_id must not be empty.")
        if self.identity_manager.agent_id != agent_id:
            raise ValueError("The supplied agent_id does not match this device.")

    def _require_online_agent(self, agent_id: str) -> None:
        self._require_local_agent(agent_id)
        if self.network_status != NETWORK_ONLINE:
            raise RuntimeError("Robot must be online before performing task operations.")

    def _clear_track_state(self, *, clear_task_registry: bool = False) -> None:
        self._published_tracks.clear()
        self._subscribed_tracks.clear()
        if clear_task_registry:
            self._task_registry.clear()
            return
        for task_entry in self._task_registry.values():
            if isinstance(task_entry, dict):
                task_entry["published_tracks"] = set()
                task_entry["subscribed_tracks"] = set()

    def _clear_identity_and_network_state(
        self,
        *,
        clear_task_registry: bool = False,
        force_stop_processing_tasks: bool = False,
    ) -> None:
        if force_stop_processing_tasks:
            for task_id in self._get_processing_task_ids():
                self._stop_task_tracks(task_id)
                if task_id in self._task_registry:
                    self._task_registry[task_id]["status"] = TASK_TERMINATED
        self.identity_manager.clear()
        self.disconnect_all(close_http=False, clear_task_registry=clear_task_registry)

    def _get_processing_task_ids(self) -> list[str]:
        return [
            task_id
            for task_id, task_entry in self._task_registry.items()
            if isinstance(task_entry, dict) and task_entry.get("status") == TASK_PROCESSING
        ]

    def _has_processing_tasks(self) -> bool:
        return bool(self._get_processing_task_ids())

    def _stop_task_tracks(self, task_id: str) -> None:
        task_entry = self._task_registry.get(task_id)
        if not isinstance(task_entry, dict):
            return
        published_tracks = task_entry.get("published_tracks")
        if isinstance(published_tracks, set):
            for track_key in list(published_tracks):
                namespace, track = self._split_track_key(track_key)
                if self.moq_pub_client is not None:
                    try:
                        self.moq_pub_client.unpublish(namespace, track)
                    except Exception:
                        self._logger.exception("Failed to unpublish task_id=%s track=%s", task_id, track_key)
                self._published_tracks.discard(track_key)
                published_tracks.discard(track_key)
        subscribed_tracks = task_entry.get("subscribed_tracks")
        if isinstance(subscribed_tracks, set):
            for track_key in list(subscribed_tracks):
                namespace, track = self._split_track_key(track_key)
                if self.moq_sub_client is not None:
                    try:
                        self.moq_sub_client.unsubscribe(namespace, track, self.identity_manager.agent_id or self.agent_name)
                    except Exception:
                        self._logger.exception("Failed to unsubscribe task_id=%s track=%s", task_id, track_key)
                self._subscribed_tracks.discard(track_key)
                subscribed_tracks.discard(track_key)

    def _track_task_published(self, task_id: str, track_key: str) -> None:
        task_entry = self._task_registry.get(task_id)
        if not isinstance(task_entry, dict):
            return
        task_entry.setdefault("published_tracks", set())
        published_tracks = task_entry.setdefault("published_tracks", set())
        if isinstance(published_tracks, set):
            published_tracks.add(track_key)

    def _track_task_subscribed(self, task_id: str, track_key: str) -> None:
        task_entry = self._task_registry.get(task_id)
        if not isinstance(task_entry, dict):
            return
        task_entry.setdefault("subscribed_tracks", set())
        subscribed_tracks = task_entry.setdefault("subscribed_tracks", set())
        if isinstance(subscribed_tracks, set):
            subscribed_tracks.add(track_key)

    @staticmethod
    def _summarize_task_entry(task_id: str, task_entry: dict[str, Any]) -> dict[str, Any]:
        published_tracks = task_entry.get("published_tracks", set())
        subscribed_tracks = task_entry.get("subscribed_tracks", set())
        return {
            "task_id": task_id,
            "description": task_entry.get("description"),
            "status": task_entry.get("status"),
            "requesting_agent_id": task_entry.get("requesting_agent_id"),
            "published_tracks": sorted(published_tracks) if isinstance(published_tracks, set) else [],
            "subscribed_tracks": sorted(subscribed_tracks) if isinstance(subscribed_tracks, set) else [],
        }

    @staticmethod
    def _split_track_key(track_key: str) -> tuple[str, str]:
        namespace, track = track_key.split("::", 1)
        return namespace, track

    def _build_ws_message(self, message_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return WebSocketMessage(
            type=message_type,
            timestamp=self._utc_timestamp(),
            payload=payload,
        ).model_dump(mode="json")

    def _report_pipeline_log(
        self,
        *,
        protocol: str,
        destination: str,
        method: str,
        url: str,
        headers: dict[str, str] | None,
        abstract: str,
        content: Any,
        task_id: str | None = None,
    ) -> None:
        if self.pipeline_log_reporter is None:
            return
        self.pipeline_log_reporter.report(
            source="ACN SDK",
            destination=destination,
            protocol=protocol,
            method=method,
            url=url,
            headers=headers,
            abstract=abstract,
            content=content,
            task_id=task_id,
        )

    @staticmethod
    def _stringify_result(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)

    @staticmethod
    def _dispatch_message_callback(callback_name: str, callback: Any | None, payload: dict[str, Any]) -> None:
        if callback is None:
            return
        try:
            callback(payload)
        except TypeError as exc:
            raise TypeError(f"{callback_name} must accept a single payload argument.") from exc

    @staticmethod
    def _generate_task_id() -> str:
        return f"task-{secrets.token_hex(3)[:5]}"

    @staticmethod
    def _track_key(namespace: str, track: str) -> str:
        return f"{namespace}::{track}"
