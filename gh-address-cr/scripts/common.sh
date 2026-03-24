#!/usr/bin/env bash
set -euo pipefail

skill_scripts_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skill_root_dir="$(cd "$skill_scripts_dir/.." && pwd)"

# State directory (progress + audit logs).
#
# This skill is commonly installed "globally" under $CODEX_HOME/skills. Writing state into the
# skill installation directory is undesirable (can be read-only, and mixes state across repos).
#
# We default to a user cache directory as a pragmatic tradeoff:
# - Cache is usually stable enough over a PR's lifetime.
# - If it is purged, the workflow can be rebuilt from GitHub thread state; the main downside is
#   potential repeated work (e.g., re-processing threads).
#
# Override with GH_ADDRESS_CR_STATE_DIR to pin state somewhere else (repo-local or user-state).
if [[ -n "${GH_ADDRESS_CR_STATE_DIR:-}" ]]; then
  state_dir="$GH_ADDRESS_CR_STATE_DIR"
else
  home_dir="${HOME:-}"
  os_name="$(uname -s 2>/dev/null || echo unknown)"
  case "$os_name" in
    Darwin)
      cache_base="${XDG_CACHE_HOME:-${home_dir:+$home_dir/Library/Caches}}"
      ;;
    *)
      cache_base="${XDG_CACHE_HOME:-${home_dir:+$home_dir/.cache}}"
      ;;
  esac
  if [[ -z "${cache_base:-}" ]]; then
    echo "Unable to determine a user cache directory (XDG_CACHE_HOME/HOME missing)." >&2
    echo "Set GH_ADDRESS_CR_STATE_DIR to a writable directory and retry." >&2
    exit 2
  fi
  state_dir="$cache_base/gh-address-cr"
fi

require_tools() {
  local missing=()
  for t in "$@"; do
    if ! command -v "$t" >/dev/null 2>&1; then
      missing+=("$t")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Missing required tool(s): ${missing[*]}" >&2
    echo "Please install them and retry." >&2
    exit 2
  fi
}

ensure_state_dir() {
  mkdir -p "$state_dir"
}

normalize_repo() {
  local repo="$1"
  echo "${repo//\//__}"
}

handled_threads_file() {
  local repo="${1:-}"
  local pr_number="${2:-}"
  if [[ -n "$repo" && -n "$pr_number" ]]; then
    local repo_key
    repo_key="$(normalize_repo "$repo")"
    echo "$state_dir/${repo_key}__pr${pr_number}__handled_threads.txt"
    return
  fi
  # Backward-compat fallback
  echo "$state_dir/handled_threads.txt"
}

snapshot_file() {
  local repo="$1"
  local pr_number="$2"
  local repo_key
  repo_key="$(normalize_repo "$repo")"
  echo "$state_dir/${repo_key}__pr${pr_number}__threads.jsonl"
}

cleanup_pr_state_files() {
  local repo="$1"
  local pr_number="$2"
  local snapshot
  local repo_key
  local handled
  snapshot="$(snapshot_file "$repo" "$pr_number")"
  repo_key="$(normalize_repo "$repo")"
  handled="$(handled_threads_file "$repo" "$pr_number")"
  rm -f \
    "$snapshot" \
    "$snapshot.prev" \
    "$handled" \
    "$state_dir/${repo_key}__pr${pr_number}__current_unresolved_ids.txt" \
    "$state_dir/${repo_key}__pr${pr_number}__prev_unresolved_ids.txt" \
    "$state_dir/${repo_key}__pr${pr_number}__new_unresolved_ids.txt"
}

audit_log_file() {
  local repo="$1"
  local pr_number="$2"
  local repo_key
  repo_key="$(normalize_repo "$repo")"
  echo "$state_dir/${repo_key}__pr${pr_number}__audit.jsonl"
}

audit_summary_file() {
  local repo="$1"
  local pr_number="$2"
  local repo_key
  repo_key="$(normalize_repo "$repo")"
  echo "$state_dir/${repo_key}__pr${pr_number}__audit_summary.md"
}

json_escape_string() {
  local input="${1:-}"
  jq -Rn --arg s "$input" '$s'
}

sha256_of_file() {
  local file="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
    return
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
    return
  fi
  echo "sha256-unavailable"
}

audit_event() {
  local action="$1"
  local status="$2"
  local repo="$3"
  local pr_number="$4"
  local audit_id="${5:-default}"
  local message="${6:-}"
  local details_json="${7:-{}}"
  local log_file
  local timestamp
  local details_safe
  timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  log_file="$(audit_log_file "$repo" "$pr_number")"
  details_safe="$(jq -cn --arg d "$details_json" '$d | fromjson? // {"_raw_details": $d, "_parse_error": true}')"

  ensure_state_dir
  jq -nc \
    --arg ts "$timestamp" \
    --arg action "$action" \
    --arg status "$status" \
    --arg repo "$repo" \
    --arg pr "$pr_number" \
    --arg audit_id "$audit_id" \
    --arg message "$message" \
    --argjson details "$details_safe" \
    '{timestamp:$ts, action:$action, status:$status, repo:$repo, pr:$pr, audit_id:$audit_id, message:$message, details:$details}' \
    >> "$log_file"
}

is_handled_thread() {
  local thread_id="$1"
  local repo="${2:-}"
  local pr_number="${3:-}"
  local handled_file
  handled_file="$(handled_threads_file "$repo" "$pr_number")"
  [[ -f "$handled_file" ]] && grep -Fxq "$thread_id" "$handled_file"
}

mark_handled_thread() {
  local thread_id="$1"
  local repo="${2:-}"
  local pr_number="${3:-}"
  local handled_file
  handled_file="$(handled_threads_file "$repo" "$pr_number")"
  touch "$handled_file"
  if ! grep -Fxq "$thread_id" "$handled_file"; then
    echo "$thread_id" >> "$handled_file"
  fi
}
