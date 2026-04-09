#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
resolve_script="$script_dir/resolve_thread.sh"

dry_run=false
yes=false
repo=""
pr_number=""
audit_id="default"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=true
      shift
      ;;
    --yes)
      yes=true
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
    --audit-id)
      audit_id="${2:-}"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--dry-run] [--yes] [--repo <owner/repo> --pr <number>] [--audit-id <id>] <approved_threads_file>"
      echo
      echo "Approved list format (breaking change):"
      echo "  - One approved thread per line: APPROVED <thread_id>"
      echo "  - Empty lines and # comments are allowed"
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 [--dry-run] [--yes] [--repo <owner/repo> --pr <number>] [--audit-id <id>] <approved_threads_file>" >&2
  exit 1
fi

approved_file="$1"
if [[ ! -f "$approved_file" ]]; then
  echo "Approved thread file not found: $approved_file" >&2
  exit 1
fi

if [[ "$dry_run" == false && "$yes" == false ]]; then
  echo "Refusing destructive bulk action without --yes (or use --dry-run)." >&2
  exit 1
fi

while IFS= read -r tid; do
  [[ -z "$tid" ]] && continue
  [[ "$tid" =~ ^# ]] && continue
  if [[ ! "$tid" =~ ^APPROVED[[:space:]]+([^[:space:]]+)[[:space:]]*$ ]]; then
    echo "Invalid line in approved list: '$tid'" >&2
    echo "Expected format: APPROVED <thread_id>" >&2
    exit 2
  fi
  tid="${BASH_REMATCH[1]}"
  extra_args=()
  if [[ -n "$repo" && -n "$pr_number" ]]; then
    extra_args+=(--repo "$repo" --pr "$pr_number" --audit-id "$audit_id")
  fi
  if [[ "$dry_run" == true ]]; then
    if [[ ${#extra_args[@]} -gt 0 ]]; then
      bash "$resolve_script" --dry-run "${extra_args[@]}" "$tid"
    else
      bash "$resolve_script" --dry-run "$tid"
    fi
  else
    if [[ ${#extra_args[@]} -gt 0 ]]; then
      bash "$resolve_script" "${extra_args[@]}" "$tid"
    else
      bash "$resolve_script" "$tid"
    fi
  fi
done < "$approved_file"
