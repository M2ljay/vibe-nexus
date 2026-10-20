#!/bin/bash
# Unpack downloaded community extension archives and bundle each one's
# index.js (local requires inlined, packages external) for run.js.
# Usage: prep_community.sh <dir with *.bin> <out bundles dir>
set -u
SRC="$1"; OUT="$2"
E=/opt/npm-tools/node_modules/esbuild/bin/esbuild
WORK=$(mktemp -d)
mkdir -p "$OUT"
for f in "$SRC"/*.bin; do
  n=$(basename "$f" .bin)
  d="$WORK/$n"; mkdir -p "$d"
  python3 -I "$(dirname "$0")/la_extract.py" "$f" "$d" 2>/dev/null || unzip -o -q "$f" -d "$d" 2>/dev/null
  entry=$(find "$d" -maxdepth 3 -name index.js -not -path '*/node_modules/*' | awk '{ print length, $0 }' | sort -n | head -1 | cut -d' ' -f2-)
  if [ -z "$entry" ]; then echo "noindex $n"; continue; fi
  $E "$entry" --bundle --platform=node --format=cjs --log-level=error --packages=external \
     --loader:.json=json --outfile="$OUT/$n.js" 2>/dev/null || { cp "$entry" "$OUT/$n.js"; echo "rawcopy $n"; }
done
rm -rf "$WORK"
