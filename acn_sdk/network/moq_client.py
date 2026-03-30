from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

from moq import FullTrackName, MOQPublisher, MOQSubscriber, PublishedObject, ReceivedObject


class MoQClient:
    def __init__(
        self,
        host: str,
        remote_port: int,
        local_port: int,
        role: str,
        on_object_received: Callable[[str, str, bytes], None] | None = None,
    ) -> None:
        self.host = host
        self.remote_port = remote_port
        self.local_port = local_port
        self.role = role
        self.on_object_received = on_object_received
        self._logger = logging.getLogger(self.__class__.__name__)
        self._subscriptions: dict[str, list[str]] = defaultdict(list)
        self._subscription_tracks: dict[str, FullTrackName] = {}
        self._published_tracks: set[str] = set()
        self._publication_tracks: dict[str, FullTrackName] = {}
        self._object_counters: dict[str, int] = defaultdict(int)
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None

        self._publisher: MOQPublisher | None = None
        self._subscriber: MOQSubscriber | None = None

    def connect(self) -> None:
        self._logger.info(
            "Connecting MoQ client role=%s local_port=%s remote=%s:%s",
            self.role,
            self.local_port,
            self.host,
            self.remote_port,
        )
        self._loop = asyncio.new_event_loop()
        if self.role == "publisher":
            self._publisher = MOQPublisher(self.host, self.remote_port)
            self._publisher.set_handlers(
                on_connected=lambda: self._logger.info("MoQ publisher connected to relay"),
                on_disconnected=lambda: self._logger.info("MoQ publisher disconnected from relay"),
                on_publication_accepted=lambda track_name: self._logger.info("MoQ publication accepted track=%s", track_name),
                on_publication_rejected=lambda track_name, reason: self._logger.warning(
                    "MoQ publication rejected track=%s reason=%s",
                    track_name,
                    reason,
                ),
            )
            connected = self._run_async(self._publisher.connect())
        elif self.role == "subscriber":
            self._subscriber = MOQSubscriber(self.host, self.remote_port)
            self._subscriber.set_handlers(
                on_connected=lambda: self._logger.info("MoQ subscriber connected to relay"),
                on_disconnected=lambda: self._logger.info("MoQ subscriber disconnected from relay"),
                on_object_received=self._handle_received_object,
                on_subscription_accepted=lambda track_name: self._logger.info("MoQ subscription accepted track=%s", track_name),
                on_subscription_rejected=lambda track_name, reason: self._logger.warning(
                    "MoQ subscription rejected track=%s reason=%s",
                    track_name,
                    reason,
                ),
            )
            connected = self._run_async(self._subscriber.connect())
        else:
            raise ValueError(f"Unsupported MoQ role: {self.role}")

        if not connected:
            raise RuntimeError(f"Failed to connect MoQ {self.role} to {self.host}:{self.remote_port}")

        self._connected = True
        self._logger.info(
            "MoQ client connected role=%s local_port=%s remote=%s:%s",
            self.role,
            self.local_port,
            self.host,
            self.remote_port,
        )

    def publish(self, namespace: str, track: str) -> None:
        if self._publisher is None:
            raise RuntimeError("MoQ publisher is not connected.")
        full_track_name = self._build_full_track_name(namespace, track)
        published = self._run_async(self._publisher.publish(full_track_name))
        if not published:
            raise RuntimeError(f"Failed to publish track: {self._track_key(namespace, track)}")
        track_key = self._track_key(namespace, track)
        self._published_tracks.add(track_key)
        self._publication_tracks[track_key] = full_track_name
        self._logger.info("MoQ publish namespace=%s track=%s", namespace, track)

    def send_object(self, namespace: str, track: str, payload: bytes) -> None:
        if self._publisher is None:
            raise RuntimeError("MoQ publisher is not connected.")
        track_key = self._track_key(namespace, track)
        if track_key not in self._published_tracks:
            raise RuntimeError(f"Track is not published: {track_key}")
        object_id = self._object_counters[track_key]
        self._object_counters[track_key] += 1
        full_track_name = self._build_full_track_name(namespace, track)
        self._run_async(
            self._publisher.send_object(
                full_track_name,
                PublishedObject(group_id=0, object_id=object_id, payload=payload, use_datagram=True),
            )
        )
        self._logger.info(
            "MoQ send object namespace=%s track=%s object_id=%s payload_size=%s",
            namespace,
            track,
            object_id,
            len(payload),
        )

    def subscribe(self, namespace: str, track: str, subscriber_id: str) -> None:
        if self._subscriber is None:
            raise RuntimeError("MoQ subscriber is not connected.")
        full_track_name = self._build_full_track_name(namespace, track)
        subscribed = self._run_async(self._subscriber.subscribe(full_track_name))
        if not subscribed:
            raise RuntimeError(f"Failed to subscribe track: {self._track_key(namespace, track)}")
        track_key = self._track_key(namespace, track)
        self._subscriptions[track_key].append(subscriber_id)
        self._subscription_tracks[track_key] = full_track_name
        self._logger.info(
            "MoQ subscribe namespace=%s track=%s subscriber=%s",
            namespace,
            track,
            subscriber_id,
        )

    def simulate_incoming_object(self, namespace: str, track: str, payload: bytes) -> None:
        self._logger.info(
            "MoQ simulate incoming object namespace=%s track=%s payload_size=%s",
            namespace,
            track,
            len(payload),
        )
        if self.on_object_received is not None:
            self.on_object_received(namespace, track, payload)

    def pump(self, duration: float = 0.1) -> None:
        if self._loop is None:
            raise RuntimeError("MoQ event loop is not initialized.")
        self._run_async(asyncio.sleep(duration))

    def is_published(self, namespace: str, track: str) -> bool:
        return self._track_key(namespace, track) in self._published_tracks

    def is_subscribed(self, namespace: str, track: str, subscriber_id: str) -> bool:
        return subscriber_id in self._subscriptions.get(self._track_key(namespace, track), [])

    def disconnect(self) -> None:
        self._logger.info(
            "Disconnecting MoQ client role=%s local_port=%s remote=%s:%s",
            self.role,
            self.local_port,
            self.host,
            self.remote_port,
        )
        if self._loop is not None:
            self._run_async(self._shutdown_clients())
        self._subscriptions.clear()
        self._published_tracks.clear()
        self._object_counters.clear()
        self._connected = False
        if self._loop is not None:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()
            self._loop = None
        self._publisher = None
        self._subscriber = None
        self._logger.info(
            "MoQ client disconnected role=%s local_port=%s remote=%s:%s",
            self.role,
            self.local_port,
            self.host,
            self.remote_port,
        )

    def close(self) -> None:
        self.disconnect()

    def _handle_received_object(self, obj: ReceivedObject) -> None:
        if self.on_object_received is None or self._subscriber is None:
            return
        track_name = self._subscriber._track_aliases.get(obj.track_alias)
        if track_name is None:
            self._logger.warning("Received object for unknown track_alias=%s", obj.track_alias)
            return
        namespace = "/" + "/".join(segment.decode("utf-8") for segment in track_name.namespace)
        track = track_name.track_name.decode("utf-8")
        self.on_object_received(namespace, track, obj.payload)

    def _run_async(self, coroutine: Coroutine[Any, Any, object]) -> object:
        if self._loop is None:
            raise RuntimeError("MoQ event loop is not initialized.")
        return self._loop.run_until_complete(coroutine)

    async def _shutdown_clients(self) -> None:
        if self._publisher is not None:
            for track_key, full_track_name in list(self._publication_tracks.items()):
                try:
                    await self._publisher.unpublish(full_track_name)
                except Exception as exc:
                    self._logger.warning("Failed to unpublish track=%s error=%s", track_key, exc)
            publisher_session = getattr(self._publisher, "_session", None)
            if publisher_session is not None:
                publisher_session.close()
                self._publisher._session = None
            publisher_client = getattr(self._publisher, "_client", None)
            if publisher_client is not None:
                await publisher_client.aclose()
                self._publisher._client = None
            elif hasattr(self._publisher, "disconnect"):
                self._publisher.disconnect()
        if self._subscriber is not None:
            for track_key, full_track_name in list(self._subscription_tracks.items()):
                try:
                    await self._subscriber.unsubscribe(full_track_name)
                except Exception as exc:
                    self._logger.warning("Failed to unsubscribe track=%s error=%s", track_key, exc)
            object_task = getattr(self._subscriber, "_object_task", None)
            if object_task is not None:
                object_task.cancel()
                await asyncio.gather(object_task, return_exceptions=True)
                self._subscriber._object_task = None
            subscriber_session = getattr(self._subscriber, "_session", None)
            if subscriber_session is not None:
                subscriber_session.close()
                self._subscriber._session = None
            subscriber_client = getattr(self._subscriber, "_client", None)
            if subscriber_client is not None:
                await subscriber_client.aclose()
                self._subscriber._client = None
            elif hasattr(self._subscriber, "disconnect"):
                self._subscriber.disconnect()
        self._publication_tracks.clear()
        self._subscription_tracks.clear()

    @staticmethod
    def _build_full_track_name(namespace: str, track: str) -> FullTrackName:
        normalized = namespace.strip("/")
        namespace_parts = [] if not normalized else [segment.encode("utf-8") for segment in normalized.split("/")]
        return FullTrackName(namespace_parts, track.encode("utf-8"))

    @staticmethod
    def _track_key(namespace: str, track: str) -> str:
        return f"{namespace}::{track}"
