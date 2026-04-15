#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys

from post_reply import submit_pending_reviews_result
from python_common import audit_event, gh_write_cmd, github_viewer_login, is_transient_gh_failure, list_pending_review_ids

def chunk_actions(actions: list[dict], max_size: int) -> list[list[dict]]:
    return [actions[i:i + max_size] for i in range(0, len(actions), max_size)]


def item_result(
    *,
    status: str,
    error: str | None = None,
    reply_url: str | None = None,
    resolved: bool | None = None,
) -> dict:
    return {
        "status": status,
        "error": error,
        "reply_url": reply_url,
        "resolved": resolved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch execute GitHub review thread actions.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", dest="pr_number", required=True)
    parser.add_argument("--audit-id", default="default")
    args = parser.parse_args()

    raw_input = sys.stdin.read().strip()
    if not raw_input:
        print("{}", file=sys.stdout)
        return 0

    try:
        actions = json.loads(raw_input)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON input: {exc}", file=sys.stderr)
        return 1

    if not actions:
        print("{}", file=sys.stdout)
        return 0

    login = github_viewer_login()

    results = {}
    had_error = False
    
    # GraphQL limits node size, chunking to safe size (e.g. 20 operations per request)
    for chunk in chunk_actions(actions, 20):
        query_parts = []
        variables = {}
        flags = []
        executable_actions = []

        for action in chunk:
            thread_id = action.get("thread_id")
            if not thread_id:
                had_error = True
                results[action["item_id"]] = item_result(
                    status="failed",
                    error="GitHub thread actions require thread_id.",
                )
                continue
            i = len(executable_actions)
            if action.get("reply_body"):
                query_parts.append(f"reply{i}: addPullRequestReviewThreadReply(input:{{pullRequestReviewThreadId: $reply{i}_threadId, body: $reply{i}_body}}) {{ comment {{ url }} }}")
                variables[f"reply{i}_threadId"] = "ID!"
                variables[f"reply{i}_body"] = "String!"
                flags.extend(["-F", f"reply{i}_threadId={thread_id}", "-F", f"reply{i}_body={action['reply_body']}"])
            
            if action.get("resolve"):
                query_parts.append(f"resolve{i}: resolveReviewThread(input:{{threadId: $resolve{i}_threadId}}) {{ thread {{ id isResolved }} }}")
                variables[f"resolve{i}_threadId"] = "ID!"
                flags.extend(["-F", f"resolve{i}_threadId={thread_id}"])
            executable_actions.append(action)

        if not query_parts:
            continue

        var_str = ", ".join(f"${k}: {v}" for k, v in variables.items())
        query = f"mutation({var_str}) {{ {' '.join(query_parts)} }}"
        
        cmd = ["gh", "api", "graphql", "-f", f"query={query}"] + flags
        result = gh_write_cmd(cmd, check=False)

        payload = {}
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            if result.returncode != 0:
                had_error = True
                status = "retryable" if is_transient_gh_failure(result.stderr, result.stdout, result.returncode) else "unknown"
                for action in executable_actions:
                    results[action["item_id"]] = item_result(
                        status=status,
                        error=result.stderr or "GraphQL request failed",
                    )
                continue
        errors = payload.get("errors")
        data = payload.get("data") or {}
        if errors or result.returncode != 0:
            had_error = True

        for i, action in enumerate(executable_actions):
            item_id = action["item_id"]
            reply_data = data.get(f"reply{i}")
            if reply_data is None and len(executable_actions) == 1:
                reply_data = data.get("addPullRequestReviewThreadReply")
            resolve_data = data.get(f"resolve{i}")
            if resolve_data is None and len(executable_actions) == 1:
                resolve_data = data.get("resolveReviewThread")

            reply_url = reply_data.get("comment", {}).get("url") if action.get("reply_body") and reply_data else None
            resolved = resolve_data.get("thread", {}).get("isResolved") if action.get("resolve") and resolve_data else None

            # Check for specific field errors if GraphQL returned partial success
            if errors:
                item_errors = [e["message"] for e in errors if any(p.startswith(f"reply{i}") or p.startswith(f"resolve{i}") for p in e.get("path", []))]
                if item_errors:
                    results[item_id] = item_result(status="failed", error="; ".join(item_errors), reply_url=reply_url, resolved=resolved)
                    continue
                results[item_id] = item_result(status="failed", error="; ".join(e["message"] for e in errors), reply_url=reply_url, resolved=resolved)
                continue

            reply_requested = bool(action.get("reply_body"))
            resolve_requested = bool(action.get("resolve"))
            reply_succeeded = (not reply_requested) or bool(reply_url)
            resolve_succeeded = (not resolve_requested) or resolved is True

            if result.returncode == 0 and reply_succeeded and resolve_succeeded:
                results[item_id] = item_result(status="succeeded", reply_url=reply_url, resolved=resolved)
            elif result.returncode != 0 and is_transient_gh_failure(result.stderr, result.stdout, result.returncode):
                results[item_id] = item_result(status="retryable", error=result.stderr or "GraphQL request failed", reply_url=reply_url, resolved=resolved)
            else:
                results[item_id] = item_result(status="unknown", error=result.stderr or "GraphQL response was incomplete", reply_url=reply_url, resolved=resolved)

    pending_after = list_pending_review_ids(args.repo, args.pr_number, login)
    current_pending = sorted(pending_after)
    submit_result = {"status": "skipped", "submitted": [], "error": None}
    if current_pending:
        submit_result = submit_pending_reviews_result(args.repo, args.pr_number, current_pending)
        if submit_result["status"] not in {"skipped", "succeeded"}:
            had_error = True
            for value in results.values():
                if value.get("status") == "succeeded":
                    value["status"] = "unknown"
                    value["error"] = submit_result["error"] or "batch actions succeeded but review submission did not complete"

    audit_event(
        "batch_github_execute",
        "partial" if had_error else "ok",
        args.repo,
        args.pr_number,
        args.audit_id,
        "Executed batch GitHub operations",
        {
            "actions_count": len(actions),
            "pending_after": current_pending,
            "submitted": submit_result["submitted"],
            "submit_status": submit_result["status"],
            "submit_error": submit_result["error"],
            "result_status_counts": {
                "succeeded": sum(1 for value in results.values() if value.get("status") == "succeeded"),
                "failed": sum(1 for value in results.values() if value.get("status") == "failed"),
                "unknown": sum(1 for value in results.values() if value.get("status") == "unknown"),
                "retryable": sum(1 for value in results.values() if value.get("status") == "retryable"),
            },
        },
    )

    print(json.dumps(results, indent=2))
    return 1 if had_error else 0

if __name__ == "__main__":
    raise SystemExit(main())
