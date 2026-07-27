#!/usr/bin/env bash
# Update the version constant in pyproject.toml and SERVER_VERSION in
# bws-mcp-server.py in lockstep. Run from the repo root.
#
# Usage:
#     scripts/bump-version.sh 1.7.0
#
# Then:
#     - Edit CHANGELOG.md to add a [X.Y.Z] section
#     - uv lock             # refresh uv.lock
#     - git commit -am "Bump version to X.Y.Z"
#     - git tag vX.Y.Z
#     - git push --tags
#
# CI's version-sync step will fail if pyproject.toml and SERVER_VERSION
# drift apart, so use this script to keep them aligned.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 X.Y.Z" >&2
    exit 2
fi

NEW_VERSION="$1"

# Sanity: must look like X.Y.Z (semver minor).
if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
    echo "error: '$NEW_VERSION' is not a valid semver version (expected X.Y.Z or X.Y.Z-prerelease)" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYPROJECT="pyproject.toml"
SERVER="bws-mcp-server.py"

# Update pyproject.toml. Match `version = "X.Y.Z"` at start of line.
if ! grep -qE '^version = "[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?"$' "$PYPROJECT"; then
    echo "error: could not find ^version = \"X.Y.Z\" line in $PYPROJECT" >&2
    exit 1
fi
# BSD/GNU-compatible in-place edit.
sed -i.bak -E "s|^version = \"[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?\"|version = \"$NEW_VERSION\"|" "$PYPROJECT"
rm -f "$PYPROJECT.bak"

# Update SERVER_VERSION in bws-mcp-server.py. Match `SERVER_VERSION = "X.Y.Z"`.
if ! grep -qE '^SERVER_VERSION = "[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?"$' "$SERVER"; then
    echo "error: could not find ^SERVER_VERSION = \"X.Y.Z\" line in $SERVER" >&2
    exit 1
fi
sed -i.bak -E "s|^SERVER_VERSION = \"[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?\"|SERVER_VERSION = \"$NEW_VERSION\"|" "$SERVER"
rm -f "$SERVER.bak"

echo "Bumped to $NEW_VERSION:"
echo "  - $PYPROJECT:    version = \"$NEW_VERSION\""
echo "  - $SERVER:  SERVER_VERSION = \"$NEW_VERSION\""
echo
echo "Next steps:"
echo "  1. Add a [${NEW_VERSION}] entry to CHANGELOG.md"
echo "  2. uv lock   # refresh uv.lock"
echo "  3. uv run python -m tests   # verify"
echo "  4. git commit -am \"Bump version to ${NEW_VERSION}\""
echo "  5. git tag v${NEW_VERSION} && git push --tags"