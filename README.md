# bws-mcp-server

[![CI](https://github.com/EVWorth/bws-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/EVWorth/bws-mcp-server/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A small [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server that gives AI agents structured access to the [Bitwarden Secrets Manager](https://bitwarden.com/products/secrets-manager/) CLI (`bws`).

It fills a gap: every other published Bitwarden MCP server (`@bitwarden/mcp-server`, `bitwarden-mcp`, `@icoretech/warden-mcp`) wraps the **Password Manager** CLI (`bw`), which requires an interactive `BW_SESSION` token. This server wraps the **Secrets Manager** CLI (`bws`) and authenticates with a **machine-account access token** — the right primitive for an AI agent that needs API keys, deploy credentials, and other machine-to-machine secrets.

## Features

- **Read-only by default.** Metadata tools (`bws_secret_list`, `bws_project_list`, `bws_project_get`) are designed to be safe to auto-approve.
- **Sensitive tools opt-in.** `bws_secret_get` and `bws_run` return or use secret values; clients should require explicit per-session approval.
- **Stdlib only.** Single-file Python implementation, no `pip install`, no Node.js, no SDK dependency.
- **Reuses your existing `bws` install.** Thin wrapper around the official Bitwarden CLI; inherits all of its security guarantees.
- **Machine-account auth.** Same threat model as a deploy bot — no human in the loop, no master password.

## Tools

| Tool | Description |
| --- | --- |
| `bws_secret_list(project_id?, output?)` | List secrets, optionally filtered by project. Metadata only. |
| `bws_secret_get(secret_id, output?)` | Fetch a single secret by UUID. **Returns the value.** |
| `bws_project_list(output?)` | List projects visible to the machine account. |
| `bws_project_get(project_id, output?)` | Fetch a single project by UUID. |
| `bws_run(command, project_id?, ...)` | Run an arbitrary command with project secrets injected as environment variables. **The values are not in the tool result.** |
| `bws_secret_create(key, value, project_id, note?)` | Create a new secret. **Requires `BWS_MCP_ALLOW_WRITES=1`.** |
| `bws_secret_edit(secret_id, key?, value?, note?, project_id?)` | Edit an existing secret (at least one field required). **Requires `BWS_MCP_ALLOW_WRITES=1`.** |
| `bws_secret_delete(secret_ids[])` | Delete one or more secrets. **Requires `BWS_MCP_ALLOW_WRITES=1`.** |
| `bws_project_create(name)` | Create a new project. **Requires `BWS_MCP_ALLOW_WRITES=1`.** |
| `bws_project_edit(project_id, name)` | Rename a project. **Requires `BWS_MCP_ALLOW_WRITES=1`.** |
| `bws_project_delete(project_ids[])` | Delete one or more projects. **Requires `BWS_MCP_ALLOW_WRITES=1`.** |

All UUID arguments are validated before being passed to `bws`. Output is capped at 256 KiB by default to keep secrets from flooding the model context.

## Installation

### 1. Install `bws`

```bash
# Homebrew
brew install bitwarden-cli

# Or grab the binary from GitHub releases:
# https://github.com/bitwarden/sdk-sm/releases
```

Verify:
```bash
bws --version
```

### 2. Get a machine-account access token

1. Open the Bitwarden web vault for your organization
2. **Secrets Manager** → **Machine accounts** → **New machine account**
3. Copy the access token (shown once)
4. Grant the machine account read access to the project(s) you want the agent to see

### 3. Store the token

```bash
mkdir -p ~/.config/opencode
echo '0.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' > ~/.config/opencode/bws-token
chmod 600 ~/.config/opencode/bws-token
```

### 4. Install the server

```bash
curl -fsSL https://raw.githubusercontent.com/EVWorth/bws-mcp-server/main/bws-mcp-server.py \
  -o ~/.local/bin/bws-mcp-server.py
chmod 755 ~/.local/bin/bws-mcp-server.py
```

Or just copy `bws-mcp-server.py` from this repo somewhere on `PATH`.

## Configuration

### Install via APM (recommended)

This repo is published as an [APM](https://microsoft.github.io/apm/) package
(`io.github.evworth/bws-mcp-server`). Once `bws-mcp-server.py` is on `PATH`
and a token file exists at `~/.config/opencode/bws-token`, you can register
the MCP server in every detected harness with one command:

```bash
apm install io.github.evworth/bws-mcp-server
```

APM writes the server entry (and ships the `bws-secret-handling` skill) into
the right config file for each harness it detects: GitHub Copilot CLI, VS
Code, Claude Code, opencode, Cursor, Codex, Gemini, Kiro, Windsurf, and
JetBrains Copilot. The server is registered as `bws` with a default
`tools` allowlist of read-only metadata calls; `bws_secret_get` and `bws_run`
are deliberately omitted and require explicit per-call opt-in.

For GitHub-specific config see [`.github/copilot-instructions.md`](.github/copilot-instructions.md).
For ad-hoc clients see [`examples/probe.py`](examples/probe.py).

### Manual configuration

If you don't use APM, copy one of the snippets below into your harness's
MCP config. Use a stable path for `BWS_TOKEN_FILE` — the server's default
is `~/.config/opencode/bws-token`.

#### GitHub Copilot CLI

Add to `~/.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "bitwarden-secrets": {
      "type": "stdio",
      "command": "python3",
      "args": ["/home/you/.local/bin/bws-mcp-server.py"],
      "env": {
        "BWS_TOKEN_FILE": "/home/you/.config/opencode/bws-token"
      },
      "tools": ["bws_secret_list", "bws_project_list", "bws_project_get"]
    }
  }
}
```

The `tools` allowlist is intentional — `bws_secret_get` and `bws_run` are gated behind per-session `--allow-tool` so secret values never auto-flow without your approval.

#### opencode

Add to `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "bitwarden-secrets": {
      "type": "local",
      "command": ["python3", "/home/you/.local/bin/bws-mcp-server.py"],
      "environment": {
        "BWS_TOKEN_FILE": "/home/you/.config/opencode/bws-token"
      }
    }
  }
}
```

#### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bitwarden-secrets": {
      "command": "python3",
      "args": ["/home/you/.local/bin/bws-mcp-server.py"],
      "env": {
        "BWS_TOKEN_FILE": "/home/you/.config/opencode/bws-token"
      }
    }
  }
}
```

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `BWS_TOKEN_FILE` | `~/.config/opencode/bws-token` | Path to the machine-account access token file. |
| `BWS_MCP_DEBUG` | unset | If set, log debug info to stderr. |
| `BWS_MCP_MAX_OUTPUT_BYTES` | `262144` | Maximum bytes returned per tool call. |

## Safety notes

- **Treat the token file like a private key.** Mode 600, no world-readable backups, no VCS.
- **Rotate tokens on a schedule.** Bitwarden Secrets Manager tokens do not expire by default; you have to rotate them manually.
- **Limit the machine account's project access.** Grant read-only to only the projects the agent actually needs.
- **Prefer metadata tools.** If you find yourself calling `bws_secret_get` a lot, consider whether the downstream tool can be refactored to receive the value via `bws_run` instead (keeps it out of the model's context).
- **Never log or echo secret values.** The server returns them as plain text because that's the only thing the LLM can use, but every client should be configured with `tools` allowlists that gate value-returning tools.

### Two-layer gate for write tools

The six write tools — `bws_secret_create`, `bws_secret_edit`, `bws_secret_delete`, `bws_project_create`, `bws_project_edit`, `bws_project_delete` — mutate your secrets manager. They're protected by a two-layer gate; **both** layers are required to actually call them:

1. **Server-side: `BWS_MCP_ALLOW_WRITES=1`.** Without this in the server's environment, every write-tool invocation returns an `isError: true` result explaining the env var. This is the authoritative switch; client-side allowlists alone are insufficient.
2. **Client-side: harness `tools:` allowlist.** Even when the server gate is open, the harness must not auto-approve write tools. They require per-call opt-in from the user.

Default `apm.yml` only allowlists the three read-only metadata tools (`bws_secret_list`, `bws_project_list`, `bws_project_get`). To opt in to write tools, the user must:
- Add `BWS_MCP_ALLOW_WRITES=1` to the server's environment (in `apm.yml`'s `env:` block, or in the harness's MCP config `env:` for the server).
- Add the specific write tools they want to use to the harness's MCP config `tools:` array.

If you're a consumer wondering "why doesn't `bws_secret_create` show up?", check both layers.

## Why a custom server instead of `@bitwarden/mcp-server`?

The official `@bitwarden/mcp-server` package is excellent — but it wraps `bw`, the **password manager** CLI. To use it, you must:

1. Log in interactively with your master password
2. Unlock the vault
3. Maintain a session token (`BW_SESSION`) that the agent can read

That's the wrong model for a non-interactive agent that runs unattended. A machine-account access token scoped to one or two projects is.

## Development

The server is a single Python file with no dependencies. To set up a dev environment with [uv](https://docs.astral.sh/uv/):

```bash
# One-time: install uv (https://docs.astral.sh/uv/#installation)
# Then from the repo root:
uv sync                                       # create .venv with the locked Python (3.11)
uv run python -m py_compile bws-mcp-server.py # validate it parses
uv run python -m tests                        # 78 unit + dispatch tests
BWS_TOKEN_FILE=~/.config/opencode/bws-token \
  uv run python examples/probe.py             # probe with a real token
uv run python examples/probe-structured.py    # probe with the fake-bws shim
```

`uv sync` is hermetic — it reads `pyproject.toml` and `uv.lock` and creates `.venv/` pinned to CPython 3.11. No system Python is touched. Without uv:

```bash
python3 -m py_compile bws-mcp-server.py
python3 -m tests
BWS_TOKEN_FILE=... python3 examples/probe.py
python3 examples/probe-structured.py
```

## License

MIT — see [LICENSE](LICENSE).
