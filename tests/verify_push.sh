#!/bin/sh
# Verify the repo is published: PUBLIC on GitHub, clean tree, local == origin.
set -e
cd "$(dirname "$0")/.."

visibility=$(gh repo view tristan-mcinnis/local-models --json visibility -q .visibility)
[ "$visibility" = "PUBLIC" ] || { echo "visibility=$visibility"; exit 1; }

dirty=$(git status --porcelain | wc -l | tr -d ' ')
[ "$dirty" = "0" ] || { echo "dirty=$dirty"; exit 1; }

git fetch -q origin
local_head=$(git rev-parse HEAD)
remote_head=$(git rev-parse origin/main)
[ "$local_head" = "$remote_head" ] || { echo "local=$local_head remote=$remote_head"; exit 1; }

echo "PUSH_VERIFIED_PUBLIC"
