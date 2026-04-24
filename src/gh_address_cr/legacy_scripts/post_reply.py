#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

from python_common import audit_event, gh_write_cmd, github_viewer_login, is_transient_gh_failure, list_pending_review_ids


def submit_pending_reviews(repo: str, pr_number: str, review_ids: list[str]) -> list[str]:
    return submit_pending_reviews_result(repo, pr_number, review_ids)["submitted"]


def submit_pending_reviews_result(repo: str, pr_number: str, review_ids: list[str]) -> dict:
    if not review_ids:
        return {"status": "skipped", "submitted": [], "error": None}

    submitted: list[str] = []

    # We can batch GraphQL mutations if there are multiple
    query_parts = []
    variables = {}
    flags = []

    for i, node_id in enumerate(review_ids):
        query_parts.append(f"submit{i}: submitPullRequestReview(input:{{pullRequestReviewId:$id{i}, event:COMMENT, body:$body{i}}}) {{ pullRequestReview {{ id }} }}")
        variables[f"id{i}"] = "ID!"
        variables[f"body{i}"] = "String!"
        flags.extend(["-F", f"id{i}={node_id}", "-F", f"body{i}=Submitting pending automated review replies."])

    var_str = ", ".join(f"${k}: {v}" for k, v in variables.items())
    query = f"mutation({var_str}) {{ {' '.join(query_parts)} }}"

    result = gh_write_cmd(["gh", "api", "graphql", "-f", f"query={query}", *flags], check=False)
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    data = payload.get("data") or {}
    errors = payload.get("errors") or []

    for i, node_id in enumerate(review_ids):
        if f"submit{i}" in data and data[f"submit{i}"]:
            submitted.append(node_id)

    if result.returncode != 0:
        status = "retryable" if is_transient_gh_failure(result.stderr, result.stdout, result.returncode) else "unknown"
        return {"status": status, "submitted": submitted, "error": result.stderr or "submit pending reviews failed"}
    if errors:
        return {
            "status": "unknown",
            "submitted": submitted,
            "error": "; ".join(error.get("message", "GraphQL error") for error in errors),
        }
    if set(submitted) != set(review_ids):
        return {
            "status": "unknown",
            "submitted": submitted,
            "error": "submit pending reviews response was incomplete",
        }
    return {"status": "succeeded", "submitted": submitted, "error": None}


def emit_result(payload: dict, exit_code: int, *, error_message: str | None = None) -> int:
    sys.stdout.write(json.dumps(payload))
    if error_message:
        print(error_message, file=sys.stderr)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Post a reply to a GitHub PR review thread.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", dest="pr_number", default="")
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("thread_id")
    parser.add_argument("reply_markdown_file")
    args = parser.parse_args()

    reply_file = Path(args.reply_markdown_file)
    if not reply_file.exists():
        print(f"Reply file not found: {reply_file}", file=sys.stderr)
        return 1

    reply_body = reply_file.read_text(encoding="utf-8")
    can_audit = bool(args.repo and args.pr_number)

    if args.dry_run:
        print(f"[dry-run] Would reply to thread: {args.thread_id}")
        print("-----")
        print(reply_body.rstrip())
        print("-----")
        if can_audit:
            audit_event(
                "post_reply",
                "dry-run",
                args.repo,
                args.pr_number,
                args.audit_id,
                "Previewed thread reply",
                {"thread_id": args.thread_id, "reply_file": str(reply_file)},
            )
        return 0

    query = (
        "mutation($threadId:ID!,$body:String!){ "
        "addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId,body:$body}){ comment{ url } } }"
    )
    payload = {
        "action": "post_reply",
        "status": "failed",
        "thread_id": args.thread_id,
        "reply_status": "failed",
        "review_submit_status": "skipped",
        "reply_url": None,
        "submitted_pending_reviews": [],
        "error": None,
    }
    try:
        login = github_viewer_login() if args.repo and args.pr_number else ""
        result = gh_write_cmd(
            ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"threadId={args.thread_id}", "-F", f"body={reply_body}"],
            check=False,
        )
        if result.returncode != 0:
            payload["status"] = "retryable" if is_transient_gh_failure(result.stderr, result.stdout, result.returncode) else "failed"
            payload["error"] = result.stderr or "reply failed"
            if can_audit:
                audit_event(
                    "post_reply",
                    "failed",
                    args.repo,
                    args.pr_number,
                    args.audit_id,
                    "Failed to post thread reply",
                    {"thread_id": args.thread_id, "reply_file": str(reply_file), "error": payload["error"]},
                )
            return emit_result(payload, 1, error_message=payload["error"])

        try:
            reply_payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            payload["status"] = "failed"
            payload["error"] = "reply response was not valid JSON"
            if can_audit:
                audit_event(
                    "post_reply",
                    "failed",
                    args.repo,
                    args.pr_number,
                    args.audit_id,
                    "Reply response was not valid JSON",
                    {"thread_id": args.thread_id, "reply_file": str(reply_file), "error": payload["error"]},
                )
            return emit_result(payload, 1, error_message=payload["error"])
        reply_url = reply_payload.get("data", {}).get("addPullRequestReviewThreadReply", {}).get("comment", {}).get("url", "")
        if not reply_url:
            payload["status"] = "unknown"
            payload["error"] = "reply succeeded with no comment url in response"
            if can_audit:
                audit_event(
                    "post_reply",
                    "partial",
                    args.repo,
                    args.pr_number,
                    args.audit_id,
                    "Reply succeeded with no comment url in response",
                    {"thread_id": args.thread_id, "reply_file": str(reply_file), "error": payload["error"]},
                )
            return emit_result(payload, 1, error_message=payload["error"])

        payload["reply_status"] = "succeeded"
        payload["reply_url"] = reply_url

        pending_after: set[str] = set()
        submit_result = {"status": "skipped", "submitted": [], "error": None}
        if args.repo and args.pr_number:
            pending_after = list_pending_review_ids(args.repo, args.pr_number, login)
            submit_result = submit_pending_reviews_result(args.repo, args.pr_number, sorted(pending_after))
            payload["review_submit_status"] = submit_result["status"]
            payload["submitted_pending_reviews"] = submit_result["submitted"]

        if payload["review_submit_status"] in {"skipped", "succeeded"}:
            payload["status"] = "succeeded"
            if can_audit:
                audit_event(
                    "post_reply",
                    "ok",
                    args.repo,
                    args.pr_number,
                    args.audit_id,
                    "Posted thread reply",
                    {
                        "thread_id": args.thread_id,
                        "reply_file": str(reply_file),
                        "reply_url": reply_url,
                        "pending_reviews_after": sorted(pending_after),
                        "submitted_pending_reviews": submit_result["submitted"],
                    },
                )
            return emit_result(payload, 0)

        payload["status"] = "unknown"
        payload["error"] = submit_result["error"] or "reply posted but review submission did not complete"
        if can_audit:
            audit_event(
                "post_reply",
                "partial",
                args.repo,
                args.pr_number,
                args.audit_id,
                "Posted thread reply but review submission did not complete",
                {
                    "thread_id": args.thread_id,
                    "reply_file": str(reply_file),
                    "reply_url": reply_url,
                    "pending_reviews_after": sorted(pending_after),
                    "submitted_pending_reviews": submit_result["submitted"],
                    "error": payload["error"],
                },
            )
        return emit_result(payload, 1, error_message=payload["error"])
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        payload["status"] = "unknown" if payload["reply_status"] == "succeeded" else "failed"
        payload["error"] = (getattr(exc, "stderr", "") or getattr(exc, "stdout", "") or str(exc)).strip()
        if can_audit:
            audit_event(
                "post_reply",
                "partial" if payload["reply_status"] == "succeeded" else "failed",
                args.repo,
                args.pr_number,
                args.audit_id,
                "Post reply command failed",
                {"thread_id": args.thread_id, "reply_file": str(reply_file), "error": payload["error"]},
            )
        return emit_result(payload, 1, error_message=payload["error"])


if __name__ == "__main__":
    raise SystemExit(main())
