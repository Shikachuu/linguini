#!/usr/bin/env bash
# Builder-stage script: install the uv-managed Python into /usr/local and sync the project into it.
set -Eeuo pipefail

uv python install --project=/app
py="$(uv python find --project=/app --managed-python)"
[ -n "$py" ] || { echo "uv python find returned nothing" >&2; exit 1; }
prefix="$(dirname "$(dirname "$(readlink -f "$py")")")"
[ -x "$prefix/bin/python3" ] || { echo "no python3 under $prefix" >&2; exit 1; }
echo "copying $prefix into /usr/local"
cp -a "$prefix"/. /usr/local/
UV_PROJECT_ENVIRONMENT=/usr/local uv sync --project=/app --locked --no-dev --no-editable --no-managed-python --compile-bytecode
install -d -o 65532 -g 65532 -m 0750 /data
