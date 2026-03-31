from __future__ import annotations

from acn_sdk.models import TaskExecutionRequest
from acn_sdk.network.http_client import HttpClient
from acn_sdk.network.websocket_client import WebSocketClient
from acn_sdk.sdk import AcnSDK


class FakeHttpResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class FakeHttpSession:
    def __init__(self, response_payload: dict[str, object]) -> None:
        self.response_payload = response_payload
        self.requests: list[tuple[str, dict[str, object], dict[str, str] | None]] = []

    def post(self, url: str, json: dict[str, object], headers: dict[str, str] | None = None) -> FakeHttpResponse:
        self.requests.append((url, json, headers))
        return FakeHttpResponse(200, self.response_payload)

    def close(self) -> None:
        return None


class FakeWebSocketConnection:
    def __init__(self, incoming: str) -> None:
        self.incoming = incoming
        self.sent: list[str] = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.sent.append(payload)

    def recv(self) -> str:
        return self.incoming

    def close(self) -> None:
        self.closed = True


def test_http_client_logs_pretty_json_for_request_and_response(caplog) -> None:
    session = FakeHttpSession({"result": "success", "nested": {"alpha": 1, "beta": [1, 2]}})
    client = HttpClient("http://acn-agent", "http://arf", session=session, arf_session=session)

    caplog.set_level("INFO")
    client.request_task_execution(
        TaskExecutionRequest(
            agent_id="did:acn:agent:1",
            task_id="task-1",
            description="demo task",
            timestamp="2025-01-01T00:00:00Z",
        )
    )

    assert "HTTP POST http://acn-agent/acn-agent/v1/task-executions" in caplog.text
    assert '{\n  "agent_id": "did:acn:agent:1"' in caplog.text
    assert '"nested": {' in caplog.text
    assert '"beta": [\n      1,\n      2\n    ]' in caplog.text
    assert "HTTP response /acn-agent/v1/task-executions" in caplog.text


def test_websocket_client_logs_pretty_json_for_send_and_receive(caplog, monkeypatch) -> None:
    connection = FakeWebSocketConnection('{"type":"TASK_REQUEST_COLLABORATION","payload":{"a":1,"b":[2,3]}}')
    import websocket

    monkeypatch.setattr(websocket, "create_connection", lambda url: connection)

    caplog.set_level("INFO")
    client = WebSocketClient("ws://127.0.0.1:9002/ws")
    client.connect()
    client.send_json({"type": "PING", "payload": {"hello": "world", "count": 2}})
    payload = client.receive_json()

    assert payload["type"] == "TASK_REQUEST_COLLABORATION"
    assert "Sending websocket payload" in caplog.text
    assert '{\n  "type": "PING",' in caplog.text
    assert "Received websocket payload" in caplog.text
    assert '"b": [\n      2,\n      3\n    ]' in caplog.text


def test_sdk_logs_pretty_json_for_received_ws_message(caplog, sdk_environment) -> None:
    sdk = AcnSDK(robot_name="AliceAgent")
    caplog.set_level("INFO")

    sdk.handle_network_message(
        {
            "type": "TASK_REQUEST_COLLABORATION",
            "timestamp": "2025-01-01T00:00:00Z",
            "payload": {"task_id": "task-1", "src_agent_id": "did:acn:agent:peer-1"},
        }
    )

    assert "Handling network message type=TASK_REQUEST_COLLABORATION payload=" in caplog.text
    assert '{\n  "task_id": "task-1",' in caplog.text
    assert '"src_agent_id": "did:acn:agent:peer-1"' in caplog.text
