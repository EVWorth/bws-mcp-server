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
    # Newline-delimited JSON — matches bws-mcp-server.py's _encode_message.
    return json.dumps(payload).encode() + b"\n"


def read_frame(stream) -> dict | None:
    # Newline-delimited JSON — see bws-mcp-server.py's _encode_message.
    line = stream.readline()
    if not line:
        return None
    return json.loads(line)


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


def start_server(env_overrides: dict | None = None) -> tuple[subprocess.Popen, str]:
    """Spawn a server process. Returns (proc, token_file_path)."""
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
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.Popen(
        ["python3", str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return proc, token_file.name


def stop_server(proc: subprocess.Popen, label: str) -> None:
    proc.stdin.close()
    err = proc.stderr.read().decode()
    if err.strip():
        print(f"\n--- server stderr ({label}) ---")
        print(err)
    proc.wait(timeout=5)


def run_legacy_assertions(proc: subprocess.Popen) -> None:
    """Initialize, list tools, and run the read-only metadata + bws_run checks."""
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
        init.get("result", {}).get("protocolVersion") == "2025-11-25",
        "initialize.protocolVersion == 2025-11-25",
    )

    proc.stdin.write(frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    proc.stdin.flush()

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


def run_gate_closed_assertions(proc: subprocess.Popen) -> None:
    """Server with BWS_MCP_ALLOW_WRITES UNSET: write tools should refuse."""
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
    proc.stdin.write(frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    proc.stdin.flush()

    # tools/list still exposes write tools — they exist in the schema;
    # the gate is at invocation time, not listing time.
    tools_res = call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    by_name = {t["name"]: t for t in tools_res["result"]["tools"]}
    for name in (
        "bws_secret_create",
        "bws_secret_edit",
        "bws_secret_delete",
        "bws_project_create",
        "bws_project_edit",
        "bws_project_delete",
    ):
        check(name in by_name, f"tools/list exposes {name}")

    # Each write tool call should return isError=True with a clear message.
    for name, args in (
        ("bws_secret_create", {"key": "k", "value": "v", "project_id": "33333333-3333-3333-3333-333333333333"}),
        ("bws_secret_edit", {"secret_id": "11111111-1111-1111-1111-111111111111", "value": "new"}),
        ("bws_secret_delete", {"secret_ids": ["11111111-1111-1111-1111-111111111111"]}),
        ("bws_project_create", {"name": "x"}),
        ("bws_project_edit", {"project_id": "33333333-3333-3333-3333-333333333333", "name": "renamed"}),
        ("bws_project_delete", {"project_ids": ["33333333-3333-3333-3333-333333333333"]}),
    ):
        res = call(proc, {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        })
        r = res.get("result", {})
        check(r.get("isError") is True, f"{name} gate-closed: isError == True")
        text = (r.get("content", [{}])[0].get("text") or "")
        check(
            "BWS_MCP_ALLOW_WRITES" in text,
            f"{name} gate-closed: error message mentions BWS_MCP_ALLOW_WRITES",
            detail=text[:200],
        )


def run_gate_open_assertions(proc: subprocess.Popen) -> None:
    """Server with BWS_MCP_ALLOW_WRITES=1: write tools should succeed."""
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
    proc.stdin.write(frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    proc.stdin.flush()

    for name, args, expect_data_type in (
        ("bws_secret_create", {"key": "k", "value": "v", "project_id": "33333333-3333-3333-3333-333333333333"}, dict),
        ("bws_secret_edit", {"secret_id": "11111111-1111-1111-1111-111111111111", "value": "new"}, dict),
        ("bws_secret_delete", {"secret_ids": ["11111111-1111-1111-1111-111111111111"]}, None),
        ("bws_project_create", {"name": "my-new-project"}, dict),
        ("bws_project_edit", {"project_id": "33333333-3333-3333-3333-333333333333", "name": "renamed"}, dict),
        ("bws_project_delete", {"project_ids": ["33333333-3333-3333-3333-333333333333"]}, None),
    ):
        res = call(proc, {
            "jsonrpc": "2.0",
            "id": 40,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        })
        r = res.get("result", {})
        check(
            r.get("isError") is False,
            f"{name} gate-open: isError == False",
            detail=str(r.get("content", [{}])[0].get("text", ""))[:200],
        )
        check("content" in r, f"{name} gate-open: has content")
        check(
            "structuredContent" in r,
            f"{name} gate-open: has structuredContent",
        )
        sc = r.get("structuredContent", {})
        check(
            sc.get("format") == "json",
            f"{name} gate-open: structuredContent.format == 'json'",
            detail=str(sc.get("format")),
        )
        if expect_data_type is not None:
            check(
                isinstance(sc.get("data"), expect_data_type),
                f"{name} gate-open: structuredContent.data is {expect_data_type.__name__}",
                detail=f"got {type(sc.get('data')).__name__}",
            )


def main() -> int:
    if not SERVER.exists():
        print(f"missing server: {SERVER}", file=sys.stderr)
        return 2
    if not (FAKE_BWS_DIR / "bws").exists():
        print(f"missing fake bws: {FAKE_BWS_DIR / 'bws'}", file=sys.stderr)
        return 2

    # --- Server 1: default (BWS_MCP_ALLOW_WRITES unset) ---
    print(">>> server with BWS_MCP_ALLOW_WRITES unset (default)")
    proc1, token1 = start_server()
    try:
        run_legacy_assertions(proc1)
        run_gate_closed_assertions(proc1)
    finally:
        stop_server(proc1, "default")
        try:
            os.unlink(token1)
        except OSError:
            pass

    # --- Server 2: BWS_MCP_ALLOW_WRITES=1 (gate open) ---
    print("\n>>> server with BWS_MCP_ALLOW_WRITES=1")
    proc2, token2 = start_server(env_overrides={"BWS_MCP_ALLOW_WRITES": "1"})
    try:
        run_gate_open_assertions(proc2)
    finally:
        stop_server(proc2, "writes-enabled")
        try:
            os.unlink(token2)
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