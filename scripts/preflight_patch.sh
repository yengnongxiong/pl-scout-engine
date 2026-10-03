#!/usr/bin/env bash
# Print the inputs for the Preflight workflow (.github/workflows/preflight.yml):
#   line 1: base commit (HEAD), line 2: gzip+base64 of every uncommitted change.
# Stages all changes (including new files) so the patch is complete.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git add -A
base=$(git rev-parse HEAD)
patch=$(git diff --cached --binary HEAD | gzip -9 | base64 -w0)
echo "$base"
echo "$patch"
echo "patch input size: ${#patch} chars (GitHub limit ~65000)" >&2
