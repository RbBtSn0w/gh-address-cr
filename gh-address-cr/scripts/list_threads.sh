#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$script_dir/common.sh"

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <owner/repo> <pr_number>" >&2
  exit 1
fi

require_tools gh jq

repo="$1"
pr_number="$2"
owner="${repo%%/*}"
name="${repo##*/}"

query='query($owner:String!,$name:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100, after:$after){
        pageInfo{ hasNextPage endCursor }
        nodes{
          id
          isResolved
          isOutdated
          path
          line
          firstComment: comments(first:1){ nodes{ url body } }
          latestComment: comments(last:1){ nodes{ url body } }
        }
      }
    }
  }
}'

cursor=""
while true; do
  if [[ -n "$cursor" ]]; then
    response="$(
      gh api graphql \
        -f query="$query" \
        -F owner="$owner" \
        -F name="$name" \
        -F number="$pr_number" \
        -F after="$cursor"
    )"
  else
    response="$(
      gh api graphql \
        -f query="$query" \
        -F owner="$owner" \
        -F name="$name" \
        -F number="$pr_number"
    )"
  fi

  echo "$response" | jq -c '.data.repository.pullRequest.reviewThreads.nodes[] |
    {
      id,
      isResolved,
      isOutdated,
      path,
      line,
      url: (.latestComment.nodes[0].url // .firstComment.nodes[0].url // null),
      body: (.latestComment.nodes[0].body // .firstComment.nodes[0].body // null),
      comment_source: (if (.latestComment.nodes | length) > 0 then "latest" elif (.firstComment.nodes | length) > 0 then "first" else "none" end),
      first_url: (.firstComment.nodes[0].url // null),
      latest_url: (.latestComment.nodes[0].url // null)
    }'

  has_next="$(echo "$response" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage')"
  if [[ "$has_next" != "true" ]]; then
    break
  fi
  cursor="$(echo "$response" | jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor')"
done
