from __future__ import annotations

import argparse
from typing import BinaryIO, Sequence
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start all local mock services.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--arf-port", type=int, default=9001)
    parser.add_argument("--acn-agent-port", type=int, default=9010)
    parser.add_argument("--agent-gw-port", type=int, default=9002)
    parser.add_argument("--moq-relay-port", type=int, default=9003)
    parser.add_argument("--cache-dir", default="data/moq-relay-cache")
    parser.add_argument("--log-dir", default="logs")
    return parser.parse_args()


def _start_process(
    log_dir: Path,
    name: str,
    argv: Sequence[str],
) -> tuple[subprocess.Popen[bytes], BinaryIO]:
    log_path = log_dir / f"{name}.log"
    log_file = log_path.open("ab")
    proc = subprocess.Popen(
        [sys.executable, *argv],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc, log_file


def main() -> int:
    args = parse_args()
    work_dir = Path.cwd()
    log_dir = (work_dir / args.log_dir).expanduser().resolve()
    cache_dir = (work_dir / args.cache_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    processes: list[tuple[str, subprocess.Popen[bytes], BinaryIO]] = []
    commands = [
        ("mock_arf", ["-m", "mock.mock_arf", "--host", args.host, "--port", str(args.arf_port)]),
        (
            "mock_acn_agent",
            [
                "-m",
                "mock.mock_acn_agent",
                "--host",
                args.host,
                "--port",
                str(args.acn_agent_port),
                "--arf-host",
                args.host,
                "--arf-port",
                str(args.arf_port),
            ],
        ),
        ("mock_agent_gw", ["-m", "mock.mock_agent_gw", "--host", args.host, "--port", str(args.agent_gw_port)]),
        (
            "mock_moq_relay",
            [
                "-m",
                "mock.mock_moq_relay",
                "--host",
                args.host,
                "--port",
                str(args.moq_relay_port),
                "--cache-dir",
                str(cache_dir),
            ],
        ),
    ]

    for name, argv in commands:
        proc, log_file = _start_process(log_dir, name, argv)
        processes.append((name, proc, log_file))
        if name == "mock_arf":
            time.sleep(1.0)

    print("Mock services started.")
    print(f"  ARF:        http://{args.host}:{args.arf_port}")
    print(f"  AcnAgent:   http://{args.host}:{args.acn_agent_port}")
    print(f"  AgentGW:    ws://{args.host}:{args.agent_gw_port}/ws")
    print(f"  MOQ Relay:  {args.host}:{args.moq_relay_port}")
    print(f"Logs are written to {log_dir}/")

    def shutdown(*_signos: object) -> None:
        for _, proc, _ in reversed(processes):
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    original_sigint = None
    original_sigterm = None
    try:
        original_sigint = signal.signal(signal.SIGINT, lambda *_: shutdown())
        original_sigterm = signal.signal(signal.SIGTERM, lambda *_: shutdown())
    except ValueError:
        # Signal handlers are unavailable if Python is not running in the main thread.
        pass

    exit_code = 0
    try:
        while processes:
            for name, proc, log_file in list(processes):
                code = proc.poll()
                if code is None:
                    continue
                if code != 0 and exit_code == 0:
                    exit_code = code
                try:
                    log_file.close()
                finally:
                    processes.remove((name, proc, log_file))
            time.sleep(0.2)
    except KeyboardInterrupt:
        shutdown()
    finally:
        shutdown()
        if original_sigint is not None:
            signal.signal(signal.SIGINT, original_sigint)
        if original_sigterm is not None:
            signal.signal(signal.SIGTERM, original_sigterm)
        for _, proc, log_file in reversed(list(processes)):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
            finally:
                try:
                    log_file.close()
                except Exception:
                    pass
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
