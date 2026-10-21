#!/bin/sh
# Package the built plugin for the fork's update channel: OUT/Nexus-Mods.zip
# (one "Nexus Mods" folder, as Decky's store zips are) and OUT/update.json.
set -e
OUT=${1:?usage: make_release.sh OUT_DIR [notes]}
NOTES=${2:-}
HERE=$(cd "$(dirname "$0")/.." && pwd)
STAGE=$(mktemp -d)
mkdir -p "$STAGE/Nexus Mods/py_modules" "$STAGE/Nexus Mods/dist" "$OUT"
cp "$HERE/main.py" "$HERE/package.json" "$HERE/plugin.json" "$HERE/LICENSE" "$HERE/README.md" "$STAGE/Nexus Mods/"
cp "$HERE/dist/index.js" "$STAGE/Nexus Mods/dist/"
find "$HERE/py_modules" -maxdepth 1 -type f \( -name '*.py' -o -name '*.json' \) -exec cp {} "$STAGE/Nexus Mods/py_modules/" \;
rm -f "$OUT/Nexus-Mods.zip"
(cd "$STAGE" && TZ=UTC find "Nexus Mods" -exec touch -t 202601010000 {} + && zip -qrX "$OUT/Nexus-Mods.zip" "Nexus Mods")
rm -rf "$STAGE"
VERSION=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" "$HERE/package.json")
HASH=$(sha256sum "$OUT/Nexus-Mods.zip" | cut -d' ' -f1)
python3 - "$OUT/update.json" "$VERSION" "$HASH" "$NOTES" <<'PY'
import json, sys
path, version, sha, notes = sys.argv[1:5]
json.dump({"version": version, "hash": sha,
           "artifact": "https://raw.githubusercontent.com/M2ljay/vibe-nexus/release/Nexus-Mods.zip",
           "notes": notes}, open(path, "w"), indent=1)
PY
echo "$VERSION $HASH"
