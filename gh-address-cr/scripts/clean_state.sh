#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

clean_tmp=false
all=false
repo=""
pr_number=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      all=true
      shift
      ;;
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --pr)
      pr_number="${2:-}"
      shift 2
      ;;
    --clean-tmp)
      clean_tmp=true
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [--repo <owner/repo> --pr <number> | --all] [--clean-tmp]"
      echo "  --repo/--pr   Clean state for a single PR (recommended)"
      echo "  --all         Remove all gh-address-cr state in state_dir"
      echo "  --clean-tmp   Also remove /tmp/gh-cr-reply*.md files"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--repo <owner/repo> --pr <number> | --all] [--clean-tmp]" >&2
      exit 1
      ;;
  esac
done

if [[ "$all" == true ]] && [[ -n "$repo" || -n "$pr_number" ]]; then
  echo "Unknown option combination: --all cannot be used with --repo/--pr" >&2
  echo "Usage: $0 [--repo <owner/repo> --pr <number> | --all] [--clean-tmp]" >&2
  exit 1
fi

if [[ -n "$repo" || -n "$pr_number" ]] && [[ -z "$repo" || -z "$pr_number" ]]; then
  echo "Usage: $0 [--repo <owner/repo> --pr <number> | --all] [--clean-tmp]" >&2
  exit 1
fi

if [[ "$all" == true ]]; then
  if [[ -d "$state_dir" ]]; then
    rm -rf "$state_dir"
    echo "Removed all state dir: $state_dir"
  else
    echo "State dir not found: $state_dir"
  fi
elif [[ -n "$repo" && -n "$pr_number" ]]; then
  ensure_state_dir
  cleanup_pr_state_files "$repo" "$pr_number"
  # Also remove PR-scoped audit outputs.
  rm -f "$(audit_log_file "$repo" "$pr_number")" "$(audit_summary_file "$repo" "$pr_number")"
  echo "Removed PR state for: $repo #$pr_number"
else
  # Backward-compat: previous versions removed the entire state directory.
  # Keep that behavior for now, but make it explicit.
  if [[ -d "$state_dir" ]]; then
    rm -rf "$state_dir"
    echo "Removed all state dir (no --repo/--pr provided): $state_dir"
  else
    echo "State dir not found: $state_dir"
  fi
fi

if [[ "$clean_tmp" == true ]]; then
  found=false
  for pattern in /tmp/gh-cr-reply*.md /tmp/reply-fixed-*.md; do
    if compgen -G "$pattern" > /dev/null; then
      rm -f $pattern
      echo "Removed temp files: $pattern"
      found=true
    fi
  done
  if [[ "$found" == false ]]; then
    echo "No matching temp reply files found in /tmp."
  fi
fi
