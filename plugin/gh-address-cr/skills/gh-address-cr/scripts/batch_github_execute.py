#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys

from post_reply import submit_pending_reviews_result
from python_common import (
    audit_event,
    gh_write_cmd,
    github_thread_reply_evidence,
    github_viewer_login,
    is_transient_gh_failure,
    list_pending_review_ids,
)

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


def item_error_messages(errors: object, alias: str) -> list[str]:
    if not isinstance(errors, list):
        return []
    messages: list[str] = []
    for entry in errors:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, list):
            continue
        if any(str(part).startswith(alias) for part in path):
            message = str(entry.get("message") or "").strip()
            if message:
                messages.append(message)
    return messages


def all_error_messages(errors: object) -> str:
    if not isinstance(errors, list):
        return ""
    messages = [str(entry.get("message") or "").strip() for entry in errors if isinstance(entry, dict)]
    return "; ".join(message for message in messages if message)


def execute_reply_phase(actions: list[dict]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for chunk in chunk_actions(actions, 20):
        query_parts = []
        variables = {}
        flags = []
        for i, action in enumerate(chunk):
            thread_id = action["thread_id"]
            query_parts.append(
                f"reply{i}: addPullRequestReviewThreadReply(input:{{pullRequestReviewThreadId: $reply{i}_threadId, body: $reply{i}_body}}) {{ comment {{ url }} }}"
            )
            variables[f"reply{i}_threadId"] = "ID!"
            variables[f"reply{i}_body"] = "String!"
            flags.extend(["-F", f"reply{i}_threadId={thread_id}", "-F", f"reply{i}_body={action['reply_body']}"])

        var_str = ", ".join(f"${key}: {value}" for key, value in variables.items())
        query = f"mutation({var_str}) {{ {' '.join(query_parts)} }}"
        result = gh_write_cmd(["gh", "api", "graphql", "-f", f"query={query}", *flags], check=False)

        payload = {}
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            if result.returncode != 0:
                status = "retryable" if is_transient_gh_failure(result.stderr, result.stdout, result.returncode) else "unknown"
                for action in chunk:
                    results[action["item_id"]] = item_result(status=status, error=result.stderr or "GraphQL request failed")
                continue
        errors = payload.get("errors")
        data = payload.get("data") or {}
        generic_error = all_error_messages(errors)

        for i, action in enumerate(chunk):
            item_id = action["item_id"]
            alias = f"reply{i}"
            reply_data = data.get(alias)
            if reply_data is None and len(chunk) == 1:
                reply_data = data.get("addPullRequestReviewThreadReply")
            reply_url = reply_data.get("comment", {}).get("url") if isinstance(reply_data, dict) else None
            specific_errors = item_error_messages(errors, alias)
            if specific_errors:
                results[item_id] = item_result(status="failed", error="; ".join(specific_errors), reply_url=reply_url)
                continue
            if generic_error:
                results[item_id] = item_result(status="failed", error=generic_error, reply_url=reply_url)
                continue
            if result.returncode == 0 and isinstance(reply_url, str) and reply_url.strip():
                results[item_id] = item_result(status="succeeded", reply_url=reply_url)
            elif result.returncode != 0 and is_transient_gh_failure(result.stderr, result.stdout, result.returncode):
                results[item_id] = item_result(status="retryable", error=result.stderr or "GraphQL request failed", reply_url=reply_url)
            else:
                results[item_id] = item_result(status="unknown", error=result.stderr or "GraphQL response was incomplete", reply_url=reply_url)
    return results


def execute_resolve_phase(actions: list[dict]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for chunk in chunk_actions(actions, 20):
        query_parts = []
        variables = {}
        flags = []
        for i, action in enumerate(chunk):
            thread_id = action["thread_id"]
            query_parts.append(f"resolve{i}: resolveReviewThread(input:{{threadId: $resolve{i}_threadId}}) {{ thread {{ id isResolved }} }}")
            variables[f"resolve{i}_threadId"] = "ID!"
            flags.extend(["-F", f"resolve{i}_threadId={thread_id}"])

        var_str = ", ".join(f"${key}: {value}" for key, value in variables.items())
        query = f"mutation({var_str}) {{ {' '.join(query_parts)} }}"
        result = gh_write_cmd(["gh", "api", "graphql", "-f", f"query={query}", *flags], check=False)

        payload = {}
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            if result.returncode != 0:
                status = "retryable" if is_transient_gh_failure(result.stderr, result.stdout, result.returncode) else "unknown"
                for action in chunk:
                    results[action["item_id"]] = item_result(status=status, error=result.stderr or "GraphQL request failed")
                continue
        errors = payload.get("errors")
        data = payload.get("data") or {}
        generic_error = all_error_messages(errors)

        for i, action in enumerate(chunk):
            item_id = action["item_id"]
            alias = f"resolve{i}"
            resolve_data = data.get(alias)
            if resolve_data is None and len(chunk) == 1:
                resolve_data = data.get("resolveReviewThread")
            resolved = resolve_data.get("thread", {}).get("isResolved") if isinstance(resolve_data, dict) else None
            specific_errors = item_error_messages(errors, alias)
            if specific_errors:
                results[item_id] = item_result(status="failed", error="; ".join(specific_errors), resolved=resolved)
                continue
            if generic_error:
                results[item_id] = item_result(status="failed", error=generic_error, resolved=resolved)
                continue
            if result.returncode == 0 and resolved is True:
                results[item_id] = item_result(status="succeeded", resolved=True)
            elif result.returncode != 0 and is_transient_gh_failure(result.stderr, result.stdout, result.returncode):
                results[item_id] = item_result(status="retryable", error=result.stderr or "GraphQL request failed", resolved=resolved)
            else:
                results[item_id] = item_result(status="unknown", error=result.stderr or "GraphQL response was incomplete", resolved=resolved)
    return results


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
    validated_actions = []
    for action in actions:
        item_id = action["item_id"]
        thread_id = action.get("thread_id")
        if not thread_id:
            results[item_id] = item_result(status="failed", error="GitHub thread actions require thread_id.")
            continue
        if action.get("resolve") and not action.get("reply_body"):
            has_reply_evidence, error = github_thread_reply_evidence(
                args.repo,
                args.pr_number,
                thread_id,
                require_tracked=True,
            )
            if not has_reply_evidence:
                results[item_id] = item_result(status="failed", error=error)
                continue
        if not action.get("reply_body") and not action.get("resolve"):
            results[item_id] = item_result(status="failed", error="GitHub thread actions require reply_body or resolve=true.")
            continue
        validated_actions.append(action)

    reply_actions = [action for action in validated_actions if action.get("reply_body")]
    reply_results = execute_reply_phase(reply_actions)

    resolve_candidates = []
    for action in validated_actions:
        if not action.get("resolve"):
            continue
        if action.get("reply_body"):
            reply_result = reply_results.get(action["item_id"])
            if not reply_result or reply_result.get("status") != "succeeded":
                continue
        resolve_candidates.append(action)
    resolve_results = execute_resolve_phase(resolve_candidates)

    for action in validated_actions:
        item_id = action["item_id"]
        reply_requested = bool(action.get("reply_body"))
        resolve_requested = bool(action.get("resolve"))
        reply_result = reply_results.get(item_id) if reply_requested else None
        resolve_result = resolve_results.get(item_id) if resolve_requested else None

        if reply_requested and resolve_requested:
            if not reply_result:
                results[item_id] = item_result(status="failed", error="Reply phase did not return a result.")
            elif reply_result.get("status") != "succeeded":
                results[item_id] = reply_result
            elif not resolve_result:
                results[item_id] = item_result(
                    status="unknown",
                    error="Resolve phase did not return a result.",
                    reply_url=reply_result.get("reply_url"),
                )
            else:
                results[item_id] = item_result(
                    status=resolve_result.get("status") or "unknown",
                    error=resolve_result.get("error"),
                    reply_url=reply_result.get("reply_url"),
                    resolved=resolve_result.get("resolved"),
                )
            continue

        if reply_requested:
            results[item_id] = reply_result or item_result(status="failed", error="Reply phase did not return a result.")
            continue

        if resolve_requested:
            results[item_id] = resolve_result or item_result(status="failed", error="Resolve phase did not return a result.")

    had_error = any(value.get("status") != "succeeded" for value in results.values())

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
