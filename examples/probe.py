#!/usr/bin/env python3
"""Hand-rolled JSON-RPC probe for bws-mcp-server.

Usage:
    BWS_TOKEN_FILE=/path/to/token python3 examples/probe.py

Drives the server over stdio using newline-delimited JSON framing (one
message per line, terminated by `\\n`) — matches the server's
`_encode_message` and works with both line-reading and byte-reading
clients. Prints the results of initialize, tools/list, and a sample
bws_secret_list call. Useful for debugging without setting up a full
MCP client.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def frame(payload: dict) -> bytes:
    # Newline-delimited JSON — matches the server's framing in
    # bws-mcp-server.py (see _encode_message). Read each message as one
    # line; the trailing \n is the message terminator.
    return json.dumps(payload).encode() + b"\n"


def read_frame(stream) -> dict | None:
    # Newline-delimited JSON — matches bws-mcp-server.py's _encode_message.
    line = stream.readline()
    if not line:
        return None
    return json.loads(line)


def call(proc, req):
    proc.stdin.write(frame(req))
    proc.stdin.flush()
    return read_frame(proc.stdout)


def main() -> int:
    token_file = os.environ.get("BWS_TOKEN_FILE")
    if not token_file:
        print("Set BWS_TOKEN_FILE to your machine-account access token file.", file=sys.stderr)
        return 2

    server_path = os.environ.get(
        "BWS_MCP_SERVER_PATH",
        os.path.join(os.path.dirname(__file__), "..", "bws-mcp-server.py"),
    )
    proc = subprocess.Popen(
        ["python3", os.path.abspath(server_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "BWS_TOKEN_FILE": token_file, "BWS_MCP_DEBUG": "1"},
    )

    try:
        init = call(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        print("initialize:", json.dumps(init["result"]["serverInfo"], indent=2))

        proc.stdin.write(frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        tools = call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        print("tools:", [t["name"] for t in tools["result"]["tools"]])

        listing = call(proc, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "bws_secret_list", "arguments": {}},
        })
        if listing["result"]["isError"]:
            print("bws_secret_list FAILED:", listing["result"]["content"][0]["text"])
        else:
            wrapped = json.loads(listing["result"]["content"][0]["text"])
            secrets = json.loads(wrapped["output"])
            print(f"\n{len(secrets)} secrets visible to the machine account:")
            for s in secrets:
                print(f"  - {s['key']:35s}  project={s.get('projectId', '?')}")
    finally:
        proc.stdin.close()
        err = proc.stderr.read().decode()
        if err.strip():
            print("\n--- server stderr ---")
            print(err)
        proc.wait(timeout=5)

    return 0


if __name__ == "__main__":
    sys.exit(main())
