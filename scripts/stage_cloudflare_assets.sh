#!/usr/bin/env bash
# Copy the public aggregate tracker into a Workers static-assets directory.
# Does not copy Python sources, fixtures, schemas, or operator docs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${CLOUDFLARE_ASSETS_DIR:-$ROOT/.cloudflare-assets}"
SITE="$OUT/impact-relay"

rm -rf "$OUT"
mkdir -p "$SITE/data" "$SITE/assets/brand"

cp "$ROOT/index.html" "$ROOT/app.js" "$ROOT/styles.css" "$ROOT/tokens.css" "$SITE/"
cp "$ROOT/data/impact-state.json" \
  "$ROOT/data/use-of-funds-public.json" \
  "$ROOT/data/impact-digests-public.json" \
  "$ROOT/data/public-evidence.json" \
  "$ROOT/data/public-impact.json" \
  "$SITE/data/"
cp "$ROOT/assets/brand/"* "$SITE/assets/brand/"

cp "$ROOT/cloudflare/_headers" "$OUT/_headers"
cp "$ROOT/cloudflare/_redirects" "$OUT/_redirects"

cat > "$OUT/index.html" <<'HTML'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Impact Relay</title>
  <meta http-equiv="refresh" content="0; url=/impact-relay/">
  <link rel="canonical" href="https://autogive.app/impact-relay/">
</head>
<body>
  <p><a href="/impact-relay/">Continue to Impact Relay</a></p>
</body>
</html>
HTML

echo "Staged Cloudflare public assets in $OUT"
