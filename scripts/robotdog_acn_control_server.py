from __future__ import annotations

import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


SERVICE_NAME = "robotdog-acn.service"
SYSTEMCTL = "/bin/systemctl"
DEFAULT_BIND = "0.0.0.0"
DEFAULT_PORT = 9005


def run_systemctl(action: str) -> tuple[int, str, str]:
    if action not in {"start", "stop", "status", "is-active"}:
        raise ValueError(f"unsupported action: {action}")
    result = subprocess.run(
        ["sudo", SYSTEMCTL, action, SERVICE_NAME],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


class ControlHandler(BaseHTTPRequestHandler):
    server_version = "RobotDogAcnControl/1.0"

    def _json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle_action(self, action: str) -> None:
        try:
            code, stdout, stderr = run_systemctl(action)
            self._json(
                200 if code == 0 else 500,
                {
                    "ok": code == 0,
                    "action": action,
                    "service": SERVICE_NAME,
                    "returncode": code,
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )
        except Exception as exc:
            self._json(500, {"ok": False, "action": action, "error": str(exc)})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._json(200, {"ok": True, "service": "robotdog-acn-control"})
        elif path == "/status":
            self._handle_action("status")
        elif path == "/is-active":
            self._handle_action("is-active")
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/start":
            self._handle_action("start")
        elif path == "/stop":
            self._handle_action("stop")
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="RobotDog ACN service control listener.")
    parser.add_argument("--bind", default=DEFAULT_BIND)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.bind, args.port), ControlHandler)
    print(f"listening on {args.bind}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
