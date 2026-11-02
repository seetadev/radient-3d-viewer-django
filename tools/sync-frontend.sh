#!/usr/bin/env bash
# Sync the shared viewer frontend from a checkout of seetadev/radient-3d-viewer.
# The viewer (app.js, vendored three/bootstrap, GLB models) and the JSON->GLB converter
# live in that repo and are NOT forked here.
#   usage: tools/sync-frontend.sh ../radient-3d-viewer
set -euo pipefail
src="${1:?path to a radient-3d-viewer checkout}"
dst="$(cd "$(dirname "$0")/.." && pwd)/app/static"
rm -rf "$dst/vendor" "$dst/models"
mkdir -p "$dst/models"
cp "$src/static/app.js" "$dst/app.js"
cp -r "$src/static/vendor" "$dst/vendor"
cp "$src"/models/*.glb "$dst/models/"
echo "synced from radient-3d-viewer @ $(git -C "$src" rev-parse HEAD)"
