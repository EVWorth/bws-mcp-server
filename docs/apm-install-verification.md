# APM install verification (issue #1)

End-to-end verification of `apm install github.com/EVWorth/bws-mcp-server`
across harnesses. Last run: 2026-07-26 against `apm-cli 0.26.0`.

## Setup

```bash
pip install apm-cli                              # 0.26.0
mkdir -p /tmp/apm-scratch && cd /tmp/apm-scratch
apm install github.com/EVWorth/bws-mcp-server --target copilot
```

A scratch repo with no harness markers must pass `--target` explicitly
(APM fails closed rather than defaulting to copilot).

## Result matrix

| Harness | Config file written | Format | `type:` value | `copilot mcp list` shows it? |
|---|---|---|---|---|
| Copilot CLI (`--target copilot`) | `~/.copilot/mcp-config.json` | JSON `mcpServers` | `"local"` | ✓ (Enabled) |
| Claude Code (`--target claude`) | `<project>/.mcp.json` | JSON `mcpServers` | `"stdio"` | n/a |
| OpenCode (`--target opencode`) | `<project>/opencode.json` | JSON `mcp` | `"local"` | n/a |

### Per-harness details

**Copilot CLI** — install succeeds; `copilot mcp get bws` reports:

```
bws
  Status: Enabled
  Type: local
  Command: python3 ${HOME}/.local/bin/bws-mcp-server.py
  Environment:
    BWS_TOKEN_FILE: ***
  Tools: bws_secret_list, bws_project_list, bws_project_get
  Source: User
```

APM writes `"type": "local"` whereas the hand-curated
`examples/copilot-mcp-config.json` uses `"type": "stdio"`. Both are
accepted by Copilot CLI (verified via `copilot mcp get bws` showing
Status: Enabled). They're synonyms from Copilot's perspective; the
display always shows `Type: local` for stdio servers regardless of the
config value.

**Claude Code** — install succeeds; writes project-scoped
`<project>/.mcp.json` (NOT user-global `~/.claude.json` even without
`-g`). Uses `"type": "stdio"`, matching Claude's documented schema.

**OpenCode** — install succeeds; writes project-scoped
`<project>/opencode.json` with `"type": "local"`, matching opencode's
schema (`mcp: { <name>: { type, command, environment } }`). Note
APM uses the key `environment` (opencode's name), not `env`.

## `tools:` allowlist

The three read-only metadata tools (`bws_secret_list`,
`bws_project_list`, `bws_project_get`) are auto-approved across all
three harnesses. Write tools (`bws_secret_create/edit/delete`,
`bws_project_create/edit/delete`) and `bws_secret_get`/`bws_run` are
absent from the auto-approve allowlist as designed; consumers must opt
in per-tool at the harness.

## Lockfile + integrity

`apm.lock.yaml` is written to the project root and pins the resolved
commit (`123b6f39`) with content hashes:

```yaml
dependencies:
- repo_url: evworth/bws-mcp-server
  name: bws-mcp-server
  host: github.com
  resolved_commit: 123b6f39acd217546e70703ab11df10a940b3228
  version: 1.0.0
  package_type: skill_bundle
  content_hash: sha256:f84f89eead97a58e936e501a350cb958b860dee1918fd7319fd9a313b9370e8d
  declared_license: MIT
```

`apm audit` reports `2 file(s) scanned -- no issues found`.

## Skill deployment

The `bws-secret-handling` skill lands at
`<project>/.agents/skills/bws-secret-handling/SKILL.md` (Agent Skills
standard). Verified content is portable — no machine-specific paths or
account UUIDs; the agent discovers the active project via
`bws_project_list`.

## Caveats

1. **Unpinned dependency warning.** APM emits `[!] 1 dependency
   unpinned: evworth/bws-mcp-server -- add #tag or #sha to prevent
   drift` for every install. Could be silenced by referencing a tag
   (`github.com/EVWorth/bws-mcp-server#v1.7.0`) instead of the implicit
   default branch. Trade-off: tracks `main` by default (good for
   development), needs explicit bump after tagging (better for
   stability).

2. **No `dependencies:` block in published `apm.yml`.** Our current
   `apm.yml` declares the MCP server only; consumers who want
   additional skills (e.g., a future `squad-conventions`) would have to
   add those separately. Not a problem today — the skill ships with
   the package itself.

3. **Cross-harness cleanup.** Running `--target <X>` after a previous
   install for `<Y>` removes the entry from `<Y>` ("Removed stale MCP
   server 'bws' from <Y>"). This is correct behavior — only the active
   target keeps the entry — but worth knowing for multi-harness users.

## Reproduce locally

```bash
# Use this exact scratch repo setup to reproduce the verification.
mkdir -p /tmp/apm-scratch && cd /tmp/apm-scratch
apm install github.com/EVWorth/bws-mcp-server --target copilot
copilot mcp get bws
apm audit

# Try other targets:
apm install github.com/EVWorth/bws-mcp-server --target claude
apm install github.com/EVWorth/bws-mcp-server --target opencode
ls .mcp.json opencode.json
cat apm.lock.yaml | head -30
```