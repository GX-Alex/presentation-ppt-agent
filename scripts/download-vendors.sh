#!/bin/bash
set -e
cd "$(dirname "$0")/.."
VENDOR_DIR="frontend/public/vendor"
mkdir -p "$VENDOR_DIR/reveal.js/theme"

echo "Downloading ECharts..."
curl -fL "https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js" \
  -o "$VENDOR_DIR/echarts.min.js"

echo "Downloading Reveal.js..."
BASE="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist"
curl -fL "$BASE/reveal.min.js"       -o "$VENDOR_DIR/reveal.js/reveal.min.js"
curl -fL "$BASE/reveal.min.css"      -o "$VENDOR_DIR/reveal.js/reveal.min.css"
curl -fL "$BASE/theme/black.min.css" -o "$VENDOR_DIR/reveal.js/theme/black.min.css"

echo "✅ Vendor files ready in $VENDOR_DIR"
