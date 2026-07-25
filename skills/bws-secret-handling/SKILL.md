---
name: bws-secret-handling
description: Reference for the Bitwarden Secrets Manager (bws) MCP server exposed by bws-mcp-server. Use when the user asks about credentials, API keys, tokens, connection strings, or any secret stored in Bitwarden; when connecting to a third-party service; or when deciding whether to store/retrieve a secret. Load before calling bws_secret_get, bws_secret_list, or bws_run.
---

# Bitwarden Secrets Manager (bws) — MCP

This skill describes how to safely use the `bws` MCP server registered by
the `io.github.evworth/bws-mcp-server` APM package.

## How auth works

The server reads a Bitwarden Secrets Manager **machine-account** access
token from `$BWS_TOKEN_FILE` (default `~/.config/opencode/bws-token`,
mode 600). The token is injected as `BWS_ACCESS_TOKEN` into every `bws`
subprocess call. It is never logged or echoed in tool results.

A machine-account token is project-scoped, not user-scoped. It is the
right threat model for non-interactive agents: no interactive session,
no vault unlock, no master-password prompt.

## The five tools

| Tool | Auto-approved? | What it returns |
| --- | --- | --- |
| `bws_project_list` | yes | All projects visible to the machine account (metadata only). |
| `bws_project_get(project_id)` | yes | One project by UUID (metadata only). |
| `bws_secret_list(project_id?)` | yes | Secrets in scope (metadata only — id, key, project, dates; never the value). |
| `bws_secret_get(secret_id)` | **no — opt in per session** | The full secret record including the value. Sensitive. |
| `bws_run(command, project_id?)` | **no — opt in per session** | Runs an arbitrary command with project secrets injected as env vars. The values themselves are NOT in the tool result, only the child process's stdout/stderr/returncode. |

Tools not in the auto-approve allowlist require explicit per-call consent
from the user. Do not assume you can call them silently.

## Conventions (always)

1. **Never display secret values in plain text.** When reporting what a
   tool returned, substitute `<redacted>` for values and reference by
   secret key name (e.g. "the Cloudflare API token
   (`cloudflare_api_token`)"). The user can look the value up themselves.
2. **Before connecting to any third-party service, check Secrets Manager
   first.** Run `bws_project_list` to discover the project(s) in scope,
   then `bws_secret_list(project_id=...)` to see if a credential
   already exists. Use it if it does. If it doesn't, ask the user before
   creating one.
3. **Never hardcode secrets** in scripts, configs, or `.env` files that
   will be committed. If a secret is needed at runtime, prefer
   `bws_run` so the value never enters your response or any file.
4. **Never store secrets in persistent memory.** Secret *names* are
   fine; *values* are not.
5. **Always report where a secret was stored** (project UUID + key) so
   the user can find, update, or rotate it later.
6. **Prefer read-only metadata tools.** Only escalate to `bws_secret_get`
   when the value is immediately required for the task at hand. Never
   fetch a secret "just to see what's there."
7. **If the token file is missing or `bws` returns 401**, surface the
   error verbatim. Do not attempt to re-authenticate — the token is a
   machine-account credential the agent cannot mint.

## Discovery flow

When the user says "connect to X" or "set up Y":

```
1. bws_project_list                              # discover projects in scope
2. bws_secret_list(project_id="<from step 1>")   # find existing credentials
3. If found: bws_secret_get(secret_id)           # opt-in, only when needed
4. If missing: ask the user where the credential should come from
```

## Failure modes

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Server fails to start: "BWS token file not found" | `$BWS_TOKEN_FILE` missing or wrong path | Tell the user; do not invent a token. |
| `bws secret get` returns rc ≠ 0 with HTTP 401 | Token expired or revoked | Tell the user; they need to mint a new machine-account access token in the Bitwarden web vault and overwrite the token file (mode 600). |
| `bws: command not found` | Bitwarden Secrets CLI not on `PATH` | Tell the user; nothing to recover from here. |
| A tool call returns a `secret_id`/`project_id` that doesn't match `^[0-9a-f-]{36}$` | Transcription error or non-Bitwarden value | Stop and ask the user to verify the ID. |
| `bws_run` returned stdout that *does* contain a secret value | The child command echoed an env var (e.g. `env`, `printenv`, debug logs) | Treat the value as leaked — rotate the secret and warn the user. |
