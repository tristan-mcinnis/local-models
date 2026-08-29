#!/bin/sh
# Publish scrub: no user-specific paths or key material in tracked files.
#
# Generic patterns live here. Machine-private tokens (employer domains, email
# addresses, hostnames) belong in .scrub-private (gitignored, one ERE per
# line) so the scanner never publishes what it scans for. This file is the
# one tracked file excluded from the scan — review it by hand.
set -e
cd "$(dirname "$0")/.."

GENERIC='/Users/[a-z]+/|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-|hf_[A-Za-z0-9]{30,}|ghp_[A-Za-z0-9]{30,}'
PATTERN="$GENERIC"
if [ -f .scrub-private ]; then
  PRIVATE=$(paste -sd'|' .scrub-private)
  [ -n "$PRIVATE" ] && PATTERN="$GENERIC|$PRIVATE"
fi

# Positive control: prove the pipeline detects a planted hit.
control=$(mktemp)
printf '/Users/nobody/leak\n' > "$control"
if ! grep -qE "$PATTERN" "$control"; then
  echo "SCRUB_SELFTEST_FAILED"; rm -f "$control"; exit 1
fi
rm -f "$control"

hits=$(git ls-files -z | grep -zv '^tests/scrub\.sh$' | xargs -0 grep -lE "$PATTERN" 2>/dev/null || true)
if [ -n "$hits" ]; then
  echo "PRIVATE CONTENT FOUND:"
  echo "$hits"
  exit 1
fi
echo "SCRUB_CLEAN"
