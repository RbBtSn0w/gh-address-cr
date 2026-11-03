#!/usr/bin/env bash
set -euo pipefail
candidate="${1:?candidate SHA required}"
[[ "$candidate" =~ ^[0-9a-f]{40}$ ]]
refs="$(git ls-remote --exit-code origin refs/heads/main)"
[[ "$refs" == "$candidate"$'\trefs/heads/main' ]]
