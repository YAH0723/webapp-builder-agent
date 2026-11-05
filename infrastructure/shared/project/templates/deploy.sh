#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

echo "[deploy] Installing frontend and backend workspace dependencies"
npm install --include=dev --include=optional --no-audit --no-fund

echo "[deploy] Building frontend and backend"
npm run build

test -s frontend/dist/index.html || { echo '[deploy] Missing frontend build output' >&2; exit 1; }
test -s backend/dist/server.js || { echo '[deploy] Missing backend build output' >&2; exit 1; }

# The server initializes the database and uses the PORT supplied by the Runner.
echo "[deploy] Starting application"
exec npm run start
