#!/bin/sh
# Build decky-nexus dist/index.js offline: Decky's globals stand in for react/@decky/ui,
# @decky/api and the react-icons it uses are vendored shims.
set -e
HERE=$(cd "$(dirname "$0")" && pwd); REPO=${1:-$HERE/../..}
${ESBUILD:-esbuild} "$REPO/src/index.tsx" --bundle --format=esm \
  --target=es2020 --jsx=automatic --charset=utf8 --legal-comments=none \
  --alias:react/jsx-runtime="$HERE/shims/jsx.cjs" --alias:react-dom="$HERE/shims/reactdom.cjs" \
  --alias:react="$HERE/shims/react.cjs" --alias:@decky/ui="$HERE/shims/ui.cjs" \
  --alias:@decky/api="$HERE/shims/api.js" --alias:react-icons/fa="$HERE/shims/fa.js" \
  --outfile="$REPO/dist/index.js"
