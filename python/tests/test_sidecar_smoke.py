"""Sidecar process smoke tests.

These tests intentionally exercise the real `python -m remnant_bridge`
entrypoint instead of importing FastAPI directly. They run only on Python
3.11/3.12, which is the supported HTTP sidecar range for the preview.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11) or sys.version_info >= (3, 13),
    reason="HTTP sidecar preview is supported on Python 3.11/3.12; Python 3.13 is skipped",
)


def test_python_module_entrypoint_serves_health(tmp_path: Path) -> None:
    port = _free_port()
    env = {
        **os.environ,
        "REMNANT_SIDECAR_PORT": str(port),
        "REMNANT_AUTH_TOKEN": "smoke-token",
        "REMNANT_DB_PATH": str(tmp_path / "smoke.db"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "remnant_bridge"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        payload = _wait_for_health(port, process)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    assert json.loads(payload) == {
        "status": "ok",
        "app": "Remnant",
        "version": "0.1.0",
    }


def test_python_module_entrypoint_serves_docs_when_enabled(tmp_path: Path) -> None:
    port = _free_port()
    env = {
        **os.environ,
        "REMNANT_SIDECAR_PORT": str(port),
        "REMNANT_AUTH_TOKEN": "smoke-token",
        "REMNANT_DB_PATH": str(tmp_path / "smoke.db"),
        "REMNANT_ENABLE_DOCS": "1",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "remnant_bridge"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_for_health(port, process)
        docs_html = _http_get(port, "/docs")
        openapi_json = _http_get(port, "/openapi.json")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    assert b"swagger-ui" in docs_html.lower()
    assert json.loads(openapi_json)["info"]["title"] == "Remnant"


def _wait_for_health(port: int, process: subprocess.Popen[str]) -> bytes:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + 15
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                "sidecar exited before /health became available\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}"
            )

        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                assert response.status == 200
                return response.read()
        except Exception as exc:  # noqa: BLE001 - retry until process is ready.
            last_error = exc
            time.sleep(0.25)

    raise AssertionError(f"sidecar did not serve /health in time: {last_error}")


def _http_get(port: int, path: str) -> bytes:
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.status == 200
        return response.read()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
