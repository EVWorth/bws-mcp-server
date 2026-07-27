# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Compatibility line.** Every release entry below records the `bws`
CLI version it was tested against. New `bws` releases don't
auto-update this; bump the version in the README's "Tested against"
line and add the new release entry when you confirm a smoke test.

## [Unreleased]

## [1.8.0] - 2026-07-26

### Added
- `docs/apm-install-verification.md` capturing the result of running
  `apm install github.com/EVWorth/bws-mcp-server` against Copilot CLI,
  Claude Code, and OpenCode (apm-cli 0.26.0). All three harnesses
  produce the expected config; `apm audit` passes; `bws` MCP server
  appears as `Status: Enabled` in `copilot mcp list`.

**Tested against:** `bws` 2.1.0.

## [1.7.0] - 2026-07-26

### Added
- `scripts/bump-version.sh X.Y.Z` — single-command version bump.
- CI version-sync check + unit test that fail if `pyproject.toml`
  version drifts from `SERVER_VERSION`.

**Tested against:** `bws` 2.1.0.

## [1.6.0] - 2026-07-26

### Added
- GitHub Actions CI: `.github/workflows/ci.yml` runs on every push and pull
  request. Uses `astral-sh/setup-uv@v4`, then `uv sync`, then runs
  `py_compile`, the 78-test `tests/` suite, and the self-contained
  `examples/probe-structured.py` (gate-closed + gate-open).
- CI badge at the top of `README.md`.
- `CHANGELOG.md` (this file) following Keep a Changelog format.

### Changed
- `SERVER_VERSION` (and `pyproject.toml` `version`) aligned at `1.6.0`
  (was `1.4.0` in `pyproject.toml` since the v1.5.0 commit, `1.5.0` in
  `SERVER_VERSION` since the same commit — now both match).

**Tested against:** `bws` 2.1.0.

## [1.5.0] - 2026-07-26

### Added
- uv-managed dev environment: `pyproject.toml`, `.python-version`, `uv.lock`.
  `uv sync` reads the lockfile and creates `.venv/` pinned to CPython 3.11;
  reproducible across machines with no system-Python intervention.
- `examples/fake-bws/bws` extended to handle the six new write subcommands.

### Changed
- `SERVER_VERSION` bumped from `1.0.0` to `1.5.0`. The source had been
  reporting itself as 1.0.0 to every MCP client since v1.0.0 shipped, while
  we'd actually released through v1.4.0.

**Tested against:** `bws` 2.1.0.

## [1.4.0] - 2026-07-26

### Added
- `tests/` directory with stdlib `unittest` suite — 78 tests covering
  argument-validation helpers (`_require_uuid`, `_optional_uuid`,
  `_output_format`, `_bool`, `_string`, `_command_list`,
  `_require_uuid_list`, `_at_least_one`, `_try_parse_json`), tool-dispatch
  invariants (TOOLS ↔ TOOL_DISPATCH, schema invariants), JSON-RPC plumbing
  (error codes, Content-Length framing), write-tool gate, and
  structuredContent emission.

## [1.3.0] - 2026-07-25

### Added
- Six write tools behind `BWS_MCP_ALLOW_WRITES=1`: `bws_secret_create`,
  `bws_secret_edit`, `bws_secret_delete`, `bws_project_create`,
  `bws_project_edit`, `bws_project_delete`.
- Two-layer gate for write tools: server-side env var (authoritative) +
  client-side harness `tools:` allowlist (auto-approve control).
- `outputSchema` and `structuredContent` on every write tool, parsed JSON
  embedded in `data` when `format=json`.
- Tool annotations per MCP 2025-06-18: `readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`.
- `examples/probe-structured.py` spawns two server instances and asserts
  both gate-closed and gate-open behaviour.

## [1.2.0] - 2026-07-25

### Added
- MCP 2025-06-18 `outputSchema` and `structuredContent` on the four
  metadata tools (`bws_secret_list`, `bws_secret_get`, `bws_project_list`,
  `bws_project_get`). When `format=json` and parsing succeeds, the parsed
  array/object lands under `structuredContent.data`.
- `examples/probe-structured.py` (initial) and `examples/fake-bws/bws`
  (initial) for self-contained testing without a real Bitwarden account.

## [1.1.0] - 2026-07-25

### Added
- APM packaging: `apm.yml` declaring the package as `bws-mcp-server` with a
  self-defined stdio MCP server entry under `dependencies.mcp`.
- `skills/bws-secret-handling/SKILL.md` — portable safety conventions for
  bws MCP use (no machine-specific paths or account UUIDs).
- `.github/copilot-instructions.md` — always-check-MCP-best-practices rule
  plus the repo's validate/run + architecture conventions.

### Changed
- Bumped `PROTOCOL_VERSION` from `2024-11-05` to `2025-06-18`.
- Added `Tool.title` and `Tool.annotations` to all five tools per MCP
  2025-06-18.
- README documents `apm install` as the primary install path.

## [1.0.0] - 2026-07-25

### Added
- Initial release.
- Single-file stdlib Python MCP server wrapping the `bws` (Bitwarden
  Secrets Manager) CLI. No runtime dependencies.
- Five read-only/run tools: `bws_secret_list`, `bws_secret_get`,
  `bws_project_list`, `bws_project_get`, `bws_run`.
- Machine-account access token auth (`BWS_TOKEN_FILE`, default
  `~/.config/opencode/bws-token`, mode 600).
- Output capped at 256 KiB per tool call to keep secrets from flooding
  the model context.
- Two hand-rolled probes: `examples/probe.py` (real-token) and the
  Content-Length framing logic in `bws-mcp-server.py` itself.

**Tested against:** `bws` 2.1.0.