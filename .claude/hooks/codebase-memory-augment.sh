#!/usr/bin/env bash
set +e

command -v mise >/dev/null 2>&1 || exit 0
mise x -C "$CLAUDE_PROJECT_DIR" -- codebase-memory-mcp hook-augment 2>/dev/null
exit 0
