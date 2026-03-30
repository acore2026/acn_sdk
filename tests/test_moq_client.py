from __future__ import annotations

from moq.encoding import FullTrackName

from acn_sdk.network.moq_client import MoQClient


class FakePublisher:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.connected = False
        self.published: list[FullTrackName] = []
        self.sent: list[tuple[FullTrackName, bytes, int]] = []

    async def connect(self) -> bool:
        self.connected = True
        return True

    async def publish(self, track_name: FullTrackName) -> bool:
        self.published.append(track_name)
        return True

    async def send_object(self, track_name: FullTrackName, obj) -> None:
        self.sent.append((track_name, obj.payload, obj.object_id))

    def disconnect(self) -> None:
        self.connected = False


class FakeSubscriber:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.connected = False
        self.subscribed: list[FullTrackName] = []
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

    def disconnect(self) -> None:
        self.connected = False


class FakeReceivedObject:
    def __init__(self, track_alias: int, payload: bytes) -> None:
        self.track_alias = track_alias
        self.payload = payload


def test_moq_publisher_client_uses_real_track_encoding(monkeypatch) -> None:
    import acn_sdk.network.moq_client as moq_client_module

    monkeypatch.setattr(moq_client_module, "MOQPublisher", FakePublisher)

    client = MoQClient("127.0.0.1", 9003, 8003, "publisher")
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
        8004,
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
