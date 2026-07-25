# bws-mcp-server — Copilot instructions

This repository is a single-file Python stdio MCP server (~574 lines, stdlib only) that wraps the `bws` (Bitwarden Secrets Manager) CLI. There is no build system, test runner, linter, or CI — `bws-mcp-server.py` *is* the project.

## Always check current MCP best practices first

This is a meta-rule that overrides "what's already in this repo." The conventions below describe how the code is written *today*; the MCP ecosystem evolves faster than this file, so any change to the server, its tools, its packaging, or its transport must be grounded in current docs before drafting a plan or diff.

Before reviewing the current state, planning an implementation, or proposing a change in this repo:

1. **MCP spec.** Fetch the current Model Context Protocol specification (https://modelcontextprotocol.io/) and confirm the protocol version, framing, error codes, tool schema shape, and transport types match what the server emits. Bump `PROTOCOL_VERSION` if the spec has moved.
2. **APM packaging.** If the change touches `apm.yml` or the package layout, re-fetch the APM manifest schema and primitive-types reference (https://microsoft.github.io/apm/). Self-defined stdio MCP entries have a specific shape that has changed before — verify against the current docs, not against this repo's prior diff.
3. **Harness MCP config.** If the change affects how a client discovers or auto-approves the server, fetch the current schema for the target harness — Copilot CLI `~/.copilot/mcp-config.json`, VS Code `.vscode/mcp.json`, Claude `.mcp.json`, opencode `opencode.json`, Cursor `.cursor/mcp.json`, Codex `.codex/config.toml`, Gemini `.gemini/settings.json`, etc. The `tools` allowlist semantics and field names differ across harnesses.
4. **`bws` CLI.** If the change touches a tool that wraps a `bws` subcommand, run `bws <subcommand> --help` against the installed binary — argument style (positional vs `--flag`) and output formats change between bws releases.
5. **Discrepancies.** If a current-doc finding contradicts something in this file, the README, `apm.yml`, or `bws-mcp-server.py`, surface the conflict to the user before changing either side. Do not silently override existing decisions on the assumption that newer is better.

The rest of this file describes *current in-repo conventions*. Use it as a starting point, not a constraint.

## Validate and run

```bash
# Syntax check
python3 -m py_compile bws-mcp-server.py

# End-to-end probe against a real token (drives JSON-RPC over stdio)
BWS_TOKEN_FILE=/path/to/token python3 examples/probe.py

# Smoke test against a stub bws: not built in. Use examples/probe.py with a
# fake token file to see the server's token-loading error path instead.
```

There is no formal test suite. Two probes cover the ground truth:

- `examples/probe.py` — drives a real token against the live `bws` CLI. Use for true end-to-end checks when you have a token.
- `examples/probe-structured.py` — uses `examples/fake-bws/bws` as a stand-in for the `bws` binary, so it runs without a real account. Specifically validates the MCP 2025-06-18 `outputSchema` + `structuredContent` path.

Add new protocol edge cases to whichever probe is closer rather than inventing a parallel framework. If a test runner is ever added (pytest, etc.), keep it deps-free or pin in a `requirements-dev.txt` rather than polluting the runtime path.

## Architecture (the big picture)

```
┌─────────────┐  JSON-RPC 2.0 over stdio  ┌──────────────────────┐
│ MCP client  │  ◄──────────────────────►  │  bws-mcp-server.py   │
│ (Copilot,   │   Content-Length frames   │                      │
│  Claude,    │                           │  handle_message()    │
│  opencode)  │                           │      ↓               │
└─────────────┘                           │  TOOL_DISPATCH[name] │
                                          │      ↓               │
                                          │  run_bws(argv)       │
                                          │      ↓               │
                                          │  subprocess.run(bws) │
                                          └──────────┬───────────┘
                                                     │ BWS_ACCESS_TOKEN env
                                                     ▼
                                              ┌──────────────┐
                                              │  bws binary  │
                                              └──────────────┘
```

Three invariants the whole file is built around:

1. **stdout is the JSON-RPC channel.** Every byte written to stdout must be a valid framed RPC message. Logging goes to stderr via `_log()`, never `print()`. Any tool that "wants to print debug info" must go through `_log()` and respect `BWS_MCP_DEBUG`.
2. **Token is loaded once at startup** via `load_token()` and passed as the `BWS_ACCESS_TOKEN` env var to every `bws` subprocess call. It is never logged, never returned in a tool result, never written to disk.
3. **All tool args are validated before reaching `bws`.** Use the `_require_uuid`, `_optional_uuid`, `_output_format`, `_bool`, `_string`, `_command_list` helpers — they exist so a single point enforces "no shell injection, no protocol injection, no surprise None types."

## Key conventions

### When adding a tool
1. Write the implementation function (signature `(token: str, args: dict) -> dict`).
2. Append a schema to the `TOOLS` list, mirroring the existing `inputSchema` shape — `additionalProperties: False` everywhere, `enum` for bounded strings, descriptions that mention the sensitivity if the tool returns values.
3. Add the function to `TOOL_DISPATCH`.
4. Run `python3 -m py_compile bws-mcp-server.py && BWS_TOKEN_FILE=… python3 examples/probe.py` to confirm it's listed in `tools/list` and behaves end-to-end.

### When adding a new bws subcommand
Read `bws <cmd> --help` carefully — argument style differs by command:
- `bws secret list [PROJECT_ID]` — **positional** project id (not `--project-id`)
- `bws secret get <SECRET_ID>` — **positional** secret id
- `bws project get <PROJECT_ID>` — **positional** project id
- `bws run [PROJECT_ID] -- <cmd>...` — **positional** project id, `--` separator before the child argv

The MCP wrappers in `tool_secret_list` / `tool_run` build argv with the id as the last positional element. Match that pattern.

### Output framing
`_tool_result()` JSON-dumps the payload as `indent=2` text inside a `content: [{type: text, ...}]` envelope. Tools return plain `dict`s; the framing wraps them. Returned secrets will be visible to whichever model is on the other end — treat them as already-leaked and design downstream clients (Copilot, Claude) to gate `bws_secret_get` / `bws_run` behind per-call approval, not auto-allow.

### Wire protocol details
- Framing: `Content-Length: N\r\n\r\n` then N bytes. The server also accepts bare newline-delimited JSON for ad-hoc clients — keep that fallback in `_read_message` unless intentionally removed.
- `notifications/initialized` and `notifications/cancelled` are notifications (no `id`) and return no response.
- JSON-RPC error codes use the standard `-32700 / -32600 / -32601 / -32602 / -32603` set. Don't invent new ones; clients key off these.

### Environment variables the server reads
| Var | Default | Purpose |
| --- | --- | --- |
| `BWS_TOKEN_FILE` | `~/.config/opencode/bws-token` | Token file path |
| `BWS_MCP_DEBUG` | unset | Verbose logging to stderr |
| `BWS_MCP_MAX_OUTPUT_BYTES` | `262144` | Per-tool output cap |
| `BWS_MCP_ALLOW_WRITES` | unset | Reserved — write tools are not implemented yet, see comment near top of file |

Adding a new env var: pick a `BWS_MCP_*` prefix, document it in the README's env-var table, and reference it via `os.environ.get(...)` — no config-file parser layer was added because the surface is too small to need one.

## What this repo is NOT

- Not a Bitwarden SDK binding. It shells out to the `bws` CLI. Anything the CLI doesn't expose, the server doesn't expose.
- Not a Password Manager integration. If a future contributor suggests wrapping `bw`, redirect them to `@bitwarden/mcp-server` instead — that's the right tool for that job and the threat model is different.
- Not a multi-tenant orchestrator. One token file, one machine account, one set of projects. Multi-tenant belongs in a different server.

## Commit / release

- Single-commit history so far. Conventional Commits are fine.
- Version bump = bump `SERVER_VERSION` near the top of `bws-mcp-server.py`. No other version pins exist (no `pyproject.toml`, no `setup.py`).
- Tag and release manually for now: `git tag v1.x.y && git push --tags`. No automation.
