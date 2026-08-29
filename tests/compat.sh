#!/bin/sh
# Backward-compat: the deployed CLIs keep the verb surface existing callers use
# (Pi local-image-analysis skill, Quick Launch, benchmark scripts), resolved
# against the LIVE registry.
set -e

for verb in list status path ask vision use unload benchmark pull add rm; do
  local-model "$verb" --help >/dev/null 2>&1 || { echo "local-model $verb missing"; exit 1; }
done
for verb in ocr describe ui extract; do
  local-image "$verb" --help >/dev/null 2>&1 || { echo "local-image $verb missing"; exit 1; }
done

# Live registry still resolves through the deployed CLIs.
local-model list | grep -q qwen3-vl || { echo "live registry lost qwen3-vl"; exit 1; }
local-model path default >/dev/null || { echo "path default failed"; exit 1; }

# OCR path (Apple Vision, no model server needed) still reads the fixture.
cd "$(dirname "$0")/.."
local-image ocr tests/fixtures/vision-test.png | grep -q 4827 || { echo "ocr lost the fixture"; exit 1; }

echo "COMPAT_OK"
