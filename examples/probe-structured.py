#!/usr/bin/env python3
"""Probe for MCP 2025-06-18 outputSchema + structuredContent on bws-mcp-server.

Self-contained: uses examples/fake-bws/bws as a stand-in for the real CLI
so the probe runs without a real Bitwarden Secrets Manager account. Sets up
a temp token file and prepends the fake-bws dir to PATH so the server picks
it up.

Asserts:
  - initialize.protocolVersion is "2025-06-18".
  - tools/list declares `outputSchema` for the four metadata tools
    (bws_secret_list, bws_secret_get, bws_project_list, bws_project_get).
  - tools/list does NOT declare `outputSchema` for bws_run.
  - tools/call for the metadata tools returns both `content` and
    `structuredContent`, with structuredContent.data parsed as the
    expected array (list calls) / object (get calls).
  - tools/call for bws_run returns ONLY `content` (no structuredContent).

Usage:
    python3 examples/probe-structured.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent
SERVER = REPO / "bws-mcp-server.py"
FAKE_BWS_DIR = HERE / "fake-bws"


def frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode()
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


def read_frame(stream) -> dict | None:
    buf = b""
    while True:
        ch = stream.read(1)
        if not ch:
            return None
        buf += ch
        if buf.endswith(b"\r\n\r\n"):
            break
    head, _, rest = buf.partition(b"\r\n\r\n")
    length = int(head.split(b":", 1)[1].strip())
    body = rest
    while len(body) < length:
        body += stream.read(length - len(body))
    return json.loads(body)


def call(proc, req):
    proc.stdin.write(frame(req))
    proc.stdin.flush()
    return read_frame(proc.stdout)


_failures = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global _failures
    if condition:
        print(f"OK   {label}")
    else:
        _failures += 1
        suffix = f" — {detail}" if detail else ""
        print(f"FAIL {label}{suffix}")


def main() -> int:
    if not SERVER.exists():
        print(f"missing server: {SERVER}", file=sys.stderr)
        return 2
    if not (FAKE_BWS_DIR / "bws").exists():
        print(f"missing fake bws: {FAKE_BWS_DIR / 'bws'}", file=sys.stderr)
        return 2

    # Temp token file. bws-mcp-server only checks non-empty.
    token_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".token", delete=False, dir=tempfile.gettempdir()
    )
    token_file.write("0.00000000-0000-0000-0000-000000000000\n")
    token_file.close()
    os.chmod(token_file.name, 0o600)

    env = {
        **os.environ,
        "BWS_TOKEN_FILE": token_file.name,
        "PATH": f"{FAKE_BWS_DIR}:{os.environ.get('PATH', '')}",
    }
    proc = subprocess.Popen(
        ["python3", str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    try:
        # 1. initialize.
        init = call(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "probe-structured", "version": "0.1.0"},
            },
        })
        check(
            init.get("result", {}).get("protocolVersion") == "2025-06-18",
            "initialize.protocolVersion == 2025-06-18",
        )

        # notifications/initialized is a notification, no id.
        proc.stdin.write(frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        # 2. tools/list.
        tools_res = call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        by_name = {t["name"]: t for t in tools_res["result"]["tools"]}

        for name in (
            "bws_secret_list",
            "bws_secret_get",
            "bws_project_list",
            "bws_project_get",
        ):
            check(
                "outputSchema" in by_name.get(name, {}),
                f"tools/list declares outputSchema for {name}",
            )

        check(
            "outputSchema" not in by_name.get("bws_run", {}),
            "tools/list does NOT declare outputSchema for bws_run",
        )

        # 3. tools/call returns content + structuredContent for metadata tools.
        for name, expected_data_type in (
            ("bws_secret_list", list),
            ("bws_project_list", list),
        ):
            res = call(proc, {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            })
            r = res.get("result", {})
            check(
                r.get("isError") is False,
                f"{name}.tools/call.isError == False",
                detail=str(r.get("content", [{}])[0].get("text", ""))[:200],
            )
            check("content" in r, f"{name}.tools/call has content")
            check("structuredContent" in r, f"{name}.tools/call has structuredContent")
            sc = r.get("structuredContent", {})
            check(
                sc.get("format") == "json",
                f"{name}.structuredContent.format == 'json'",
                detail=str(sc.get("format")),
            )
            check(
                isinstance(sc.get("data"), expected_data_type),
                f"{name}.structuredContent.data is {expected_data_type.__name__}",
                detail=f"got {type(sc.get('data')).__name__}",
            )

        # 4. bws_run emits only content (no structuredContent).
        res = call(proc, {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {"name": "bws_run", "arguments": {"command": ["echo", "hello"]}},
        })
        r = res.get("result", {})
        check("content" in r, "bws_run.tools/call has content")
        check(
            "structuredContent" not in r,
            "bws_run.tools/call has NO structuredContent",
        )

    finally:
        proc.stdin.close()
        err = proc.stderr.read().decode()
        if err.strip():
            print("\n--- server stderr ---")
            print(err)
        proc.wait(timeout=5)
        try:
            os.unlink(token_file.name)
        except OSError:
            pass

    print()
    if _failures:
        print(f"{_failures} assertion(s) FAILED")
        return 1
    print("All assertions passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())