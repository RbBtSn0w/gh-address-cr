#!/usr/bin/env bash

set -euo pipefail

FEATURE_NAME=""
BUILD_STATUS="N/A"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --feature-name)
      FEATURE_NAME="${2:-}"
      shift 2
      ;;
    --build-status)
      BUILD_STATUS="${2:-}"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage: archive-evidence.sh --feature-name <name> --build-status <PASS|FAIL|N/A>

Reads verification evidence from stdin and writes a timestamped markdown file
under .specify/evidence/<feature-name>/.
EOF
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$FEATURE_NAME" ]]; then
  echo "ERROR: --feature-name is required" >&2
  exit 1
fi

case "$BUILD_STATUS" in
  PASS|FAIL|N/A) ;;
  *)
    echo "ERROR: --build-status must be PASS, FAIL, or N/A" >&2
    exit 1
    ;;
esac

safe_feature="$(printf '%s' "$FEATURE_NAME" | tr -c 'A-Za-z0-9._-' '-')"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
evidence_dir=".specify/evidence/$safe_feature"
evidence_path="$evidence_dir/$timestamp.md"

mkdir -p "$evidence_dir"

{
  printf '# Verification Evidence: %s\n\n' "$FEATURE_NAME"
  printf '**Archived**: %s\n' "$timestamp"
  printf '**Build Status**: %s\n\n' "$BUILD_STATUS"
  cat
} > "$evidence_path"

printf '{"evidence_path":"%s","feature_name":"%s","build_status":"%s"}\n' \
  "$evidence_path" "$FEATURE_NAME" "$BUILD_STATUS"
