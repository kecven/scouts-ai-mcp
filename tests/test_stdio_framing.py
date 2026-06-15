"""Stdio transport smoke test.

The MCP stdio spec (2024-11-05 and 2025-06-18) requires JSON-RPC messages
to be delimited by newlines (NDJSON) on stdin/stdout, NOT LSP-style
``Content-Length`` framing. This test guards against regressions: we spawn
``python -m scouts_ai_mcp`` as a subprocess, write a single NDJSON
``initialize`` request, and assert that the first response frame is a
single line of valid JSON — not a ``Content-Length:`` header.

The test is intentionally narrow: it does not call the upstream API and
does not run a tool invocation. It only proves that the framing on the
stdio transport is NDJSON as the spec requires.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _spawn_server() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    # Point at a non-resolving host so any accidental live HTTP call
    # would fail loudly instead of polluting real API counters.
    env["SCOUTS_AI_BASE_URL"] = "http://127.0.0.1:1"
    env["SCOUTS_AI_TIMEOUT_S"] = "1.0"
    env["SCOUTS_AI_LOG_LEVEL"] = "WARNING"
    return subprocess.Popen(
        [PYTHON, "-m", "scouts_ai_mcp.server"],
        cwd=str(REPO_ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _read_one_line(proc: subprocess.Popen[bytes], timeout: float = 10.0) -> bytes:
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = proc.stdout.read(1)
        if not chunk:
            break
        buf.extend(chunk)
        if chunk == b"\n":
            return bytes(buf)
    raise AssertionError(f"timeout waiting for newline; got: {bytes(buf)!r}")


def test_stdio_framing_is_ndjson() -> None:
    proc = _spawn_server()
    try:
        assert proc.stdin is not None
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "stdio-framing-smoke", "version": "0.0.0"},
            },
        }
        proc.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        proc.stdin.flush()

        line = _read_one_line(proc, timeout=15.0)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)
        # Surface server stderr if it failed early — makes the test
        # diagnostic when the package can't be imported, etc.
        err = proc.stderr.read() if proc.stderr else b""
        if proc.returncode not in (0, None, -15, -9):
            pytest.fail(
                f"server exited with code {proc.returncode}; stderr:\n"
                f"{err.decode('utf-8', errors='replace')}"
            )

    # NDJSON: one JSON object terminated by a single '\n', no headers.
    assert line.endswith(b"\n"), f"line not newline-terminated: {line!r}"
    body = line.rstrip(b"\n")
    # Regression guard: framing must not be LSP-style.
    assert not body.startswith(b"Content-Length"), (
        f"stdio framing must be NDJSON; got LSP header: {body!r}"
    )
    # The server's response is a single JSON-RPC message with id=1.
    payload = json.loads(body)
    assert payload.get("jsonrpc") == "2.0"
    assert payload.get("id") == 1
    assert "result" in payload or "error" in payload
