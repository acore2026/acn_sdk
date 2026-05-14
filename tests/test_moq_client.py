from __future__ import annotations

import asyncio
import threading

from moq import FullTrackName, ReceivedObject
from moq.messages import ObjectStatus

from acn_sdk.network.moq_client import MoQClient


class FakePublisher:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.connected = False
        self.published: list[FullTrackName] = []
        self.sent: list[tuple[FullTrackName, bytes, int]] = []
        self.unpublished: list[FullTrackName] = []
        self.handlers = {}

    def set_handlers(self, **handlers) -> None:
        self.handlers.update(handlers)

    async def connect(self) -> bool:
        self.connected = True
        return True

    async def publish(self, track_name: FullTrackName) -> bool:
        self.published.append(track_name)
        return True

    async def send_object(self, track_name: FullTrackName, obj) -> None:
        self.sent.append((track_name, obj.payload, obj.object_id))

    async def unpublish(self, track_name: FullTrackName) -> None:
        self.unpublished.append(track_name)

    def disconnect(self) -> None:
        self.connected = False


class FakeSubscriber:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.connected = False
        self.subscribed: list[FullTrackName] = []
        self.unsubscribed: list[FullTrackName] = []
        self._track_aliases: dict[int, FullTrackName] = {}
        self._handlers = {}

    def set_handlers(self, **handlers) -> None:
        self._handlers.update(handlers)

    async def connect(self) -> bool:
        self.connected = True
        return True

    async def subscribe(self, track_name: FullTrackName) -> bool:
        self.subscribed.append(track_name)
        self._track_aliases[len(self.subscribed) - 1] = track_name
        return True

    async def unsubscribe(self, track_name: FullTrackName) -> None:
        self.unsubscribed.append(track_name)

    def disconnect(self) -> None:
        self.connected = False


class FakeReceivedObject:
    def __init__(self, track_alias: int, payload: bytes) -> None:
        self.track_alias = track_alias
        self.payload = payload


class BlockingSubscriber(FakeSubscriber):
    def __init__(self, host: str, port: int) -> None:
        super().__init__(host, port)
        self.subscribe_started = threading.Event()

    async def subscribe(self, track_name: FullTrackName) -> bool:
        self.subscribe_started.set()
        await asyncio.sleep(0.05)
        return await super().subscribe(track_name)


class SyncOnlyClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class HangingAsyncCloseClient:
    def __init__(self) -> None:
        self.closed = False
        self.cancelled = False

    async def aclose(self) -> None:
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    def close(self) -> None:
        self.closed = True


def test_moq_publisher_client_uses_real_track_encoding(monkeypatch) -> None:
    import acn_sdk.network.moq_client as moq_client_module

    monkeypatch.setattr(moq_client_module, "MOQPublisher", FakePublisher)

    client = MoQClient("127.0.0.1", 9003, "publisher")
    try:
        client.connect()
        client.publish("/task-123/agent-1", "Location")
        client.send_object("/task-123/agent-1", "Location", b"payload-1")
        client.send_object("/task-123/agent-1", "Location", b"payload-2")

        assert client.is_published("/task-123/agent-1", "Location") is True
        assert client._publisher is not None
        assert client._publisher.published[0].namespace == [b"task-123", b"agent-1"]
        assert client._publisher.published[0].track_name == b"Location"
        assert client._publisher.sent[0][2] == 0
        assert client._publisher.sent[1][2] == 1
    finally:
        client.disconnect()


def test_moq_subscriber_client_forwards_objects(monkeypatch) -> None:
    import acn_sdk.network.moq_client as moq_client_module

    monkeypatch.setattr(moq_client_module, "MOQSubscriber", FakeSubscriber)

    received_messages: list[tuple[str, str, bytes]] = []
    client = MoQClient(
        "127.0.0.1",
        9003,
        "subscriber",
        on_object_received=lambda namespace, track, payload: received_messages.append((namespace, track, payload)),
    )
    try:
        client.connect()
        client.subscribe("/task-123/agent-1", "Location", "agent-1")

        assert client.is_subscribed("/task-123/agent-1", "Location", "agent-1") is True
        assert client._subscriber is not None
        client._handle_received_object(FakeReceivedObject(track_alias=0, payload=b"remote"))

        assert received_messages == [("/task-123/agent-1", "Location", b"remote")]
    finally:
        client.disconnect()


def test_moq_client_disconnect_cleans_up_publications_and_subscriptions(monkeypatch) -> None:
    import acn_sdk.network.moq_client as moq_client_module

    monkeypatch.setattr(moq_client_module, "MOQPublisher", FakePublisher)
    monkeypatch.setattr(moq_client_module, "MOQSubscriber", FakeSubscriber)

    publisher = MoQClient("127.0.0.1", 9003, "publisher")
    subscriber = MoQClient("127.0.0.1", 9003, "subscriber")

    publisher.connect()
    subscriber.connect()
    publisher.publish("/task-123/agent-1", "Location")
    subscriber.subscribe("/task-123/agent-1", "Location", "agent-2")

    assert publisher._publisher is not None
    assert subscriber._subscriber is not None
    publisher_impl = publisher._publisher
    subscriber_impl = subscriber._subscriber

    publisher.disconnect()
    subscriber.disconnect()

    assert publisher_impl.unpublished[0].namespace == [b"task-123", b"agent-1"]
    assert publisher_impl.unpublished[0].track_name == b"Location"
    assert subscriber_impl.unsubscribed[0].namespace == [b"task-123", b"agent-1"]
    assert subscriber_impl.unsubscribed[0].track_name == b"Location"
    assert publisher._publisher is None
    assert subscriber._subscriber is None


def test_moq_client_serializes_loop_access_across_threads(monkeypatch) -> None:
    import acn_sdk.network.moq_client as moq_client_module

    monkeypatch.setattr(moq_client_module, "MOQSubscriber", BlockingSubscriber)

    client = MoQClient("127.0.0.1", 9003, "subscriber")
    try:
        client.connect()
        assert isinstance(client._subscriber, BlockingSubscriber)
        assert client._loop_thread is not None
        assert client._loop_thread.is_alive() is True

        subscribe_errors: list[BaseException] = []

        def run_subscribe() -> None:
            try:
                client.subscribe("/task-123/agent-1", "Location", "agent-2")
            except BaseException as exc:  # pragma: no cover - surfaced via assertions
                subscribe_errors.append(exc)

        subscribe_thread = threading.Thread(target=run_subscribe)
        subscribe_thread.start()

        assert client._subscriber.subscribe_started.wait(timeout=1.0) is True
        subscribe_thread.join(timeout=1.0)

        assert not subscribe_thread.is_alive()
        assert subscribe_errors == []
        assert client.is_subscribed("/task-123/agent-1", "Location", "agent-2") is True
    finally:
        client.disconnect()
        assert client._loop_thread is None or client._loop_thread.is_alive() is False


def test_moq_client_disconnect_falls_back_to_sync_close(monkeypatch) -> None:
    import acn_sdk.network.moq_client as moq_client_module

    monkeypatch.setattr(moq_client_module, "MOQPublisher", FakePublisher)

    client = MoQClient("127.0.0.1", 9003, "publisher")
    client.connect()
    assert client._publisher is not None
    sync_client = SyncOnlyClient()
    client._publisher._client = sync_client

    client.disconnect()

    assert sync_client.closed is True


def test_moq_client_disconnect_handles_async_close_timeout(monkeypatch) -> None:
    import acn_sdk.network.moq_client as moq_client_module

    monkeypatch.setattr(moq_client_module, "MOQPublisher", FakePublisher)
    monkeypatch.setattr(moq_client_module, "TRANSPORT_CLOSE_TIMEOUT_SECONDS", 0.01)

    client = MoQClient("127.0.0.1", 9003, "publisher")
    client.connect()
    assert client._publisher is not None
    hanging_client = HangingAsyncCloseClient()
    client._publisher._client = hanging_client

    client.disconnect()

    assert hanging_client.cancelled is True
    assert hanging_client.closed is True
    assert client._loop_thread is None
    assert client._publisher is None


def test_moq_subscriber_disconnect_cancels_object_task() -> None:
    from moq.sub.subscriber import MOQSubscriber

    async def run() -> None:
        subscriber = MOQSubscriber("127.0.0.1", 9003)
        object_task = asyncio.create_task(asyncio.sleep(60.0))
        subscriber._object_task = object_task

        subscriber.disconnect()
        await asyncio.sleep(0)

        assert subscriber._object_task is None
        assert object_task.cancelled() is True

    asyncio.run(run())


def test_moq_subscriber_get_next_object_bridges_owner_loop() -> None:
    from moq.sub.subscriber import MOQSubscriber

    subscriber = MOQSubscriber("127.0.0.1", 9003)
    owner_loop = asyncio.new_event_loop()
    owner_ready = threading.Event()
    keepalive_task: asyncio.Task[None] | None = None

    def run_owner_loop() -> None:
        nonlocal keepalive_task

        async def keepalive() -> None:
            while True:
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    break

        asyncio.set_event_loop(owner_loop)
        keepalive_task = owner_loop.create_task(keepalive())
        owner_ready.set()
        try:
            owner_loop.run_forever()
        finally:
            asyncio.set_event_loop(None)

    owner_thread = threading.Thread(target=run_owner_loop, daemon=True)
    owner_thread.start()
    assert owner_ready.wait(timeout=1.0)

    async def prepare_object() -> None:
        subscriber._reset_object_queue_for_current_loop()
        await subscriber._put_received_object(
            ReceivedObject(
                track_alias=1,
                group_id=0,
                object_id=0,
                publisher_priority=128,
                payload=b"payload",
                object_status=ObjectStatus.NORMAL,
            )
        )

    try:
        asyncio.run_coroutine_threadsafe(prepare_object(), owner_loop).result(timeout=1.0)

        async def read_object() -> ReceivedObject | None:
            return await subscriber.get_next_object(timeout=1.0)

        obj = asyncio.run(read_object())

        assert obj is not None
        assert obj.payload == b"payload"

        callback_received = threading.Event()
        callback_payloads: list[bytes] = []

        def on_object_received(obj: ReceivedObject) -> None:
            callback_payloads.append(obj.payload)
            callback_received.set()

        subscriber.set_handlers(on_object_received=on_object_received)

        async def prepare_callback_object() -> None:
            await subscriber._put_received_object(
                ReceivedObject(
                    track_alias=1,
                    group_id=0,
                    object_id=1,
                    publisher_priority=128,
                    payload=b"callback-payload",
                    object_status=ObjectStatus.NORMAL,
                )
            )

        asyncio.run_coroutine_threadsafe(prepare_callback_object(), owner_loop).result(timeout=1.0)

        assert callback_received.wait(timeout=1.0)
        assert callback_payloads == [b"callback-payload"]
    finally:
        async def cancel_owner_tasks() -> None:
            tasks: list[asyncio.Task[None]] = []
            if keepalive_task is not None:
                tasks.append(keepalive_task)
            if subscriber._object_task is not None:
                tasks.append(subscriber._object_task)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        if owner_loop.is_running():
            asyncio.run_coroutine_threadsafe(cancel_owner_tasks(), owner_loop).result(timeout=1.0)
        owner_loop.call_soon_threadsafe(owner_loop.stop)
        owner_thread.join(timeout=1.0)
        if not owner_loop.is_running():
            owner_loop.close()
