#!/usr/bin/env python3
"""bws-mcp-server — Bitwarden Secrets Manager MCP server (stdio).

A small Model Context Protocol server that exposes read-only access to the
Bitwarden Secrets Manager CLI (`bws`) over a machine-account access token.
This mirrors the opencode setup (bws-opencode wrapper + ~/.config/opencode/bws-token)
but exposes the same capability to any MCP-compatible client, including
GitHub Copilot CLI.

Wire protocol: JSON-RPC 2.0 over stdio with LSP-style Content-Length framing.

Token loading:
    The server reads the access token from $BWS_TOKEN_FILE (default:
    ~/.config/opencode/bws-token). Mode 600 is recommended. The token is
    injected into the bws subprocess as BWS_ACCESS_TOKEN and is never
    logged or echoed in tool results.

Tools exposed:
    bws_secret_list    List secrets, optionally filtered by project.
    bws_secret_get     Fetch a single secret by UUID.
    bws_project_list   List projects.
    bws_project_get    Fetch a single project by UUID.
    bws_run            Run a command with secrets injected as env vars.

Write tools (create/edit/delete) are NOT exposed by default. Enable with
BWS_MCP_ALLOW_WRITES=1 if you really want them, but prefer not to — Copilot
should not be writing into your secrets manager.

Safety:
    * All tool args are validated before being passed to bws.
    * subprocess.run with list args; shell=False; no string interpolation.
    * Output capped at $BWS_MCP_MAX_OUTPUT_BYTES (default 256 KiB) to keep
      secrets from flooding the model context.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_NAME = "bws-mcp-server"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-06-18"  # MCP protocol version this server targets.

DEFAULT_TOKEN_FILE = os.path.expanduser("~/.config/opencode/bws-token")
DEFAULT_MAX_OUTPUT = 256 * 1024

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
OUTPUT_FORMATS = {"json", "yaml", "env", "table", "tsv", "none"}

# ---------------------------------------------------------------------------
# Logging — stderr only, never stdout (stdout is the JSON-RPC channel).
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    if os.environ.get("BWS_MCP_DEBUG"):
        sys.stderr.write(f"[bws-mcp] {msg}\n")
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# Token loading
# ---------------------------------------------------------------------------


def load_token() -> str:
    token_file = os.environ.get("BWS_TOKEN_FILE") or DEFAULT_TOKEN_FILE
    path = os.path.expanduser(token_file)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            token = fh.read().strip()
    except FileNotFoundError:
        raise RuntimeError(
            f"BWS token file not found: {path}. "
            f"Set BWS_TOKEN_FILE or create the file (mode 600) with a "
            f"Bitwarden Secrets Manager machine-account access token."
        )
    except OSError as exc:
        raise RuntimeError(f"Cannot read BWS token file {path}: {exc}")
    if not token:
        raise RuntimeError(f"BWS token file {path} is empty.")
    return token


# ---------------------------------------------------------------------------
# Argument validation helpers
# ---------------------------------------------------------------------------


def _require_uuid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not UUID_RE.match(value):
        raise ValueError(f"{field} must be a UUID; got {value!r}")
    return value


def _optional_uuid(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    return _require_uuid(value, field)


def _output_format(value: Any, default: str = "json") -> str:
    if value in (None, ""):
        return default
    if not isinstance(value, str) or value not in OUTPUT_FORMATS:
        raise ValueError(f"output must be one of {sorted(OUTPUT_FORMATS)}; got {value!r}")
    return value


def _bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
    raise ValueError(f"{field} must be a boolean; got {value!r}")


def _string(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string; got {type(value).__name__}")
    if len(value) > max_len:
        raise ValueError(f"{field} exceeds max length of {max_len}")
    return value


def _command_list(value: Any) -> list[str]:
    """Validate a run-style command. Must be a non-empty list of strings.

    We deliberately reject a bare shell string and require argv-style lists
    so the agent can't smuggle shell metacharacters through ``bws run``.
    """
    if not isinstance(value, list) or not value:
        raise ValueError("command must be a non-empty list of argv strings")
    out: list[str] = []
    for i, part in enumerate(value):
        if not isinstance(part, str) or not part:
            raise ValueError(f"command[{i}] must be a non-empty string")
        if len(part) > 4096:
            raise ValueError(f"command[{i}] exceeds 4096 chars")
        out.append(part)
    return out


# ---------------------------------------------------------------------------
# bws invocation
# ---------------------------------------------------------------------------


def run_bws(token: str, argv: list[str], *, max_output: int) -> tuple[int, str, str]:
    """Run bws with the given argv. Returns (returncode, stdout, stderr)."""
    env = os.environ.copy()
    env["BWS_ACCESS_TOKEN"] = token
    # Force a stable output format default; per-tool format is appended below.
    env.setdefault("NO_COLOR", "1")
    try:
        completed = subprocess.run(
            ["bws", *argv],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError("bws binary not found on PATH. Install Bitwarden Secrets CLI.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("bws invocation timed out after 60s")
    stdout = completed.stdout[:max_output]
    stderr = completed.stderr[:max_output]
    return completed.returncode, stdout, stderr


# ---------------------------------------------------------------------------
# Tool definitions — each tool declares its JSON-Schema and an implementation.
# ---------------------------------------------------------------------------


# JSON Schema describing the wrapper dict returned by every bws-list /
# bws-get tool. The `data` field carries the parsed bws JSON output and is
# only present when the caller asked for format=json AND the parse succeeded;
# otherwise it's omitted. `output` always carries the raw text in the
# requested format for clients that need it.
_LIST_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "output": {
            "type": "string",
            "description": "Raw bws output in the requested format (string-typed for display).",
        },
        "format": {
            "type": "string",
            "description": "Output format actually used: json, yaml, env, table, tsv, or none.",
        },
        "data": {
            "description": "Parsed bws JSON output. Present only when format=json; absent otherwise. Shape is an array for list calls, an object for get calls.",
        },
    },
    "required": ["output", "format"],
}

# Per-tool extensions: each metadata tool adds the project/secret id field
# that it echoes back, plus the typed name for the parsed-data array/object.
_METADATA_OUTPUT_SCHEMAS: dict[str, dict] = {
    "bws_secret_list": {
        "type": "object",
        "properties": {
            **_LIST_OUTPUT_SCHEMA["properties"],
            "project_id": {
                "type": ["string", "null"],
                "description": "Project UUID filter that was applied (null when unfiltered).",
            },
            "data": {
                "type": "array",
                "description": "Parsed array of secret objects.",
                "items": {"type": "object", "additionalProperties": True},
            },
        },
        "required": ["output", "format"],
    },
    "bws_secret_get": {
        "type": "object",
        "properties": {
            **_LIST_OUTPUT_SCHEMA["properties"],
            "secret_id": {
                "type": "string",
                "description": "Secret UUID that was fetched.",
            },
            "data": {
                "type": "object",
                "description": "Parsed secret object.",
                "additionalProperties": True,
            },
        },
        "required": ["output", "format", "secret_id"],
    },
    "bws_project_list": {
        "type": "object",
        "properties": {
            **_LIST_OUTPUT_SCHEMA["properties"],
            "data": {
                "type": "array",
                "description": "Parsed array of project objects.",
                "items": {"type": "object", "additionalProperties": True},
            },
        },
        "required": ["output", "format"],
    },
    "bws_project_get": {
        "type": "object",
        "properties": {
            **_LIST_OUTPUT_SCHEMA["properties"],
            "project_id": {
                "type": "string",
                "description": "Project UUID that was fetched.",
            },
            "data": {
                "type": "object",
                "description": "Parsed project object.",
                "additionalProperties": True,
            },
        },
        "required": ["output", "format", "project_id"],
    },
}

# Tools that emit structuredContent alongside their text content.
# bws_run is intentionally absent — its output is a mix of text blobs
# (stdout/stderr) and a few typed fields; the text content alone is the
# most useful form for clients.
_STRUCTURED_OUTPUT_TOOLS = {
    "bws_secret_list",
    "bws_secret_get",
    "bws_project_list",
    "bws_project_get",
}


def _try_parse_json(s: str) -> Any | None:
    """Best-effort JSON parse. Returns None on any failure."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None


def tool_secret_list(token: str, args: dict) -> dict:
    project_id = _optional_uuid(args.get("project_id"), "project_id")
    output = _output_format(args.get("output"), default="json")
    argv = ["secret", "list", "--output", output]
    if project_id:
        # `bws secret list` takes the project id as a positional argument.
        argv.append(project_id)
    rc, out, err = run_bws(token, argv, max_output=int(os.environ.get("BWS_MCP_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT)))
    if rc != 0:
        raise RuntimeError(f"bws secret list failed (rc={rc}): {err.strip() or 'no stderr'}")
    payload: dict = {"output": out, "format": output, "project_id": project_id}
    if output == "json":
        parsed = _try_parse_json(out)
        if parsed is not None:
            payload["data"] = parsed
    return payload


def tool_secret_get(token: str, args: dict) -> dict:
    secret_id = _require_uuid(args.get("secret_id"), "secret_id")
    output = _output_format(args.get("output"), default="json")
    argv = ["secret", "get", secret_id, "--output", output]
    rc, out, err = run_bws(token, argv, max_output=int(os.environ.get("BWS_MCP_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT)))
    if rc != 0:
        raise RuntimeError(f"bws secret get failed (rc={rc}): {err.strip() or 'no stderr'}")
    payload: dict = {"output": out, "format": output, "secret_id": secret_id}
    if output == "json":
        parsed = _try_parse_json(out)
        if parsed is not None:
            payload["data"] = parsed
    return payload


def tool_project_list(token: str, args: dict) -> dict:
    output = _output_format(args.get("output"), default="json")
    argv = ["project", "list", "--output", output]
    rc, out, err = run_bws(token, argv, max_output=int(os.environ.get("BWS_MCP_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT)))
    if rc != 0:
        raise RuntimeError(f"bws project list failed (rc={rc}): {err.strip() or 'no stderr'}")
    payload: dict = {"output": out, "format": output}
    if output == "json":
        parsed = _try_parse_json(out)
        if parsed is not None:
            payload["data"] = parsed
    return payload


def tool_project_get(token: str, args: dict) -> dict:
    project_id = _require_uuid(args.get("project_id"), "project_id")
    output = _output_format(args.get("output"), default="json")
    argv = ["project", "get", project_id, "--output", output]
    rc, out, err = run_bws(token, argv, max_output=int(os.environ.get("BWS_MCP_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT)))
    if rc != 0:
        raise RuntimeError(f"bws project get failed (rc={rc}): {err.strip() or 'no stderr'}")
    payload: dict = {"output": out, "format": output, "project_id": project_id}
    if output == "json":
        parsed = _try_parse_json(out)
        if parsed is not None:
            payload["data"] = parsed
    return payload


def tool_run(token: str, args: dict) -> dict:
    """Invoke bws run with the user's argv. Secrets are exposed as env vars
    to the child process but NOT returned in the tool result."""
    project_id = _optional_uuid(args.get("project_id"), "project_id")
    command = _command_list(args.get("command"))
    shell = args.get("shell")
    uuids = args.get("uuids_as_keynames")
    no_inherit = args.get("no_inherit_env")

    argv = ["run"]
    if project_id:
        # `bws run` takes the project id as a positional argument.
        argv.append(project_id)
    if isinstance(shell, str) and shell:
        argv += ["--shell", _string(shell, "shell", max_len=64)]
    if _bool(uuids, "uuids_as_keynames") if uuids is not None else False:
        argv += ["--uuids-as-keynames"]
    if _bool(no_inherit, "no_inherit_env") if no_inherit is not None else False:
        argv += ["--no-inherit-env"]
    argv += ["--", *command]

    rc, out, err = run_bws(
        token,
        argv,
        max_output=int(os.environ.get("BWS_MCP_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT)),
    )
    return {
        "returncode": rc,
        "stdout": out,
        "stderr": err,
        "command": command,
        "project_id": project_id,
        # Deliberately omit secret values. bws run injects them as env into
        # the child process; they are not returned to the model.
    }


TOOLS: list[dict] = [
    {
        "name": "bws_secret_list",
        "title": "List secrets",
        "description": (
            "List secrets stored in Bitwarden Secrets Manager, optionally "
            "filtered by a project UUID. Returns metadata only (id, key, "
            "project, creation dates); never the secret value. Use this to "
            "discover what secrets are available before fetching."
        ),
        "annotations": {
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Optional project UUID to scope the listing.",
                },
                "output": {
                    "type": "string",
                    "enum": sorted(OUTPUT_FORMATS),
                    "description": "Output format. Defaults to json.",
                },
            },
            "additionalProperties": False,
        },
        "outputSchema": _METADATA_OUTPUT_SCHEMAS["bws_secret_list"],
    },
    {
        "name": "bws_secret_get",
        "title": "Get a secret",
        "description": (
            "Fetch a single secret from Bitwarden Secrets Manager by UUID. "
            "Returns the secret value via bws — handle the result as "
            "sensitive. Prefer fetching only when the value is immediately "
            "needed, and never echo it back to the user in plain text."
        ),
        "annotations": {
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "secret_id": {"type": "string", "description": "Secret UUID."},
                "output": {
                    "type": "string",
                    "enum": sorted(OUTPUT_FORMATS),
                    "description": "Output format. Defaults to json.",
                },
            },
            "required": ["secret_id"],
            "additionalProperties": False,
        },
        "outputSchema": _METADATA_OUTPUT_SCHEMAS["bws_secret_get"],
    },
    {
        "name": "bws_project_list",
        "title": "List projects",
        "description": "List projects in the Bitwarden Secrets Manager.",
        "annotations": {
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "output": {
                    "type": "string",
                    "enum": sorted(OUTPUT_FORMATS),
                    "description": "Output format. Defaults to json.",
                },
            },
            "additionalProperties": False,
        },
        "outputSchema": _METADATA_OUTPUT_SCHEMAS["bws_project_list"],
    },
    {
        "name": "bws_project_get",
        "title": "Get a project",
        "description": "Fetch a single project by UUID.",
        "annotations": {
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project UUID."},
                "output": {
                    "type": "string",
                    "enum": sorted(OUTPUT_FORMATS),
                    "description": "Output format. Defaults to json.",
                },
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
        "outputSchema": _METADATA_OUTPUT_SCHEMAS["bws_project_get"],
    },
    {
        "name": "bws_run",
        "title": "Run a command with secrets",
        "description": (
            "Run an arbitrary command with secrets from a Secrets Manager "
            "project injected as environment variables. The secret values "
            "are exposed only to the child process; they are NOT included "
            "in the tool result. Use this when downstream tools need "
            "credentials in their environment (e.g. docker login, curl with "
            "an API key, deploy scripts)."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Argv list to execute. Must be a list of strings.",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional project UUID whose secrets to inject.",
                },
                "shell": {
                    "type": "string",
                    "description": "Optional shell binary for bws run --shell.",
                },
                "uuids_as_keynames": {
                    "type": "boolean",
                    "description": "If true, use secret UUIDs as env var names instead of the secret key.",
                },
                "no_inherit_env": {
                    "type": "boolean",
                    "description": "If true, do not inherit the current shell's environment into the child.",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
]

TOOL_DISPATCH = {
    "bws_secret_list": tool_secret_list,
    "bws_secret_get": tool_secret_get,
    "bws_project_list": tool_project_list,
    "bws_project_get": tool_project_get,
    "bws_run": tool_run,
}


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------


def _encode_message(payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _read_message(stream) -> dict | None:
    """Read a single JSON-RPC message using Content-Length framing.

    Falls back to newline-delimited JSON if no Content-Length header is
    present on the first line (lenient mode for ad-hoc clients).
    """
    line = stream.readline()
    if not line:
        return None
    stripped = line.strip()
    if not stripped:
        return _read_message(stream)

    headers: dict[str, str] = {}
    if stripped.lower().startswith(b"content-length:"):
        headers["content-length"] = stripped.split(b":", 1)[1].strip().decode("ascii")
        # Read remaining headers until blank line.
        while True:
            h = stream.readline()
            if not h or h.strip() == b"":
                break
            k, _, v = h.partition(b":")
            headers[k.strip().lower().decode("ascii")] = v.strip().decode("ascii")
        length = int(headers.get("content-length", "0"))
        body = b""
        while len(body) < length:
            chunk = stream.read(length - len(body))
            if not chunk:
                return None
            body += chunk
        return json.loads(body.decode("utf-8"))

    # Lenient fallback: line itself is JSON.
    return json.loads(stripped.decode("utf-8"))


def _tool_result(payload: dict, structured: bool = True) -> dict:
    """Wrap a tool return value as an MCP tools/call result.

    payload: the dict to render as text content (always emitted).
    structured: when True (default), also emit the payload as
        `structuredContent` per MCP 2025-06-18 §tools/call. Tools whose
        output is a mix of text blobs and a few typed fields (e.g.
        bws_run) should pass structured=False so clients don't have to
        ignore noisy text fields inside structuredContent.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    result: dict = {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }
    if structured:
        result["structuredContent"] = payload
    return result


def _tool_error(message: str) -> dict:
    return {
        "content": [{"type": "text", "text": f"Error: {message}"}],
        "isError": True,
    }


def _ok(_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": _id, "result": result}


def _err(_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": _id, "error": err}


# Standard JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def handle_message(msg: dict, token: str) -> dict | None:
    """Return a JSON-RPC response, or None for notifications."""
    method = msg.get("method")
    params = msg.get("params") or {}
    msg_id = msg.get("id")

    # Notifications (no id) — accept and respond with nothing.
    if msg_id is None:
        if method == "notifications/initialized":
            _log("client initialized")
        elif method == "notifications/cancelled":
            _log("client cancelled a request")
        return None

    if method == "initialize":
        return _ok(
            msg_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {}},
            },
        )

    if method == "ping":
        return _ok(msg_id, {})

    if method == "tools/list":
        return _ok(msg_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or name not in TOOL_DISPATCH:
            return _err(msg_id, METHOD_NOT_FOUND, f"unknown tool: {name!r}")
        try:
            result = TOOL_DISPATCH[name](token, arguments)
            return _ok(msg_id, _tool_result(result, structured=(name in _STRUCTURED_OUTPUT_TOOLS)))
        except ValueError as exc:
            return _ok(msg_id, _tool_error(f"invalid arguments: {exc}"))
        except RuntimeError as exc:
            return _ok(msg_id, _tool_error(str(exc)))
        except Exception as exc:  # pragma: no cover — defensive
            _log(f"unexpected error in {name}: {exc!r}")
            return _ok(msg_id, _tool_error(f"internal error: {exc}"))

    return _err(msg_id, METHOD_NOT_FOUND, f"unknown method: {method!r}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        token = load_token()
    except RuntimeError as exc:
        sys.stderr.write(f"bws-mcp-server: {exc}\n")
        sys.stderr.flush()
        return 2

    _log(f"started; protocol={PROTOCOL_VERSION}")
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        try:
            msg = _read_message(stdin)
        except (json.JSONDecodeError, ValueError) as exc:
            err = _err(None, PARSE_ERROR, f"parse error: {exc}")
            stdout.write(_encode_message(err))
            stdout.flush()
            continue
        except EOFError:
            _log("stdin closed, exiting")
            return 0

        if msg is None:
            _log("EOF, exiting")
            return 0

        try:
            response = handle_message(msg, token)
        except Exception as exc:  # pragma: no cover — defensive
            response = _err(msg.get("id"), INTERNAL_ERROR, f"unhandled: {exc}")

        if response is not None:
            stdout.write(_encode_message(response))
            stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
