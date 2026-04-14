#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from python_common import audit_event, run_cmd


def current_login() -> str:
    response = run_cmd(["gh", "api", "user"], check=True)
    payload = json.loads(response.stdout)
    return payload["login"]


def list_pending_review_ids(repo: str, pr_number: str, login: str) -> set[int]:
    page = 1
    pending: set[int] = set()
    while True:
        response = run_cmd(["gh", "api", f"repos/{repo}/pulls/{pr_number}/reviews?per_page=100&page={page}"], check=True)
        reviews = json.loads(response.stdout)
        if not reviews:
            break
        for review in reviews:
            if review.get("state") != "PENDING":
                continue
            if (review.get("user") or {}).get("login") != login:
                continue
            pending.add(review["id"])
        page += 1
    return pending


def submit_pending_reviews(repo: str, pr_number: str, review_ids: list[int]) -> list[int]:
    submitted: list[int] = []
    for review_id in review_ids:
        run_cmd(
            [
                "gh",
                "api",
                f"repos/{repo}/pulls/{pr_number}/reviews/{review_id}/events",
                "-X",
                "POST",
                "-f",
                "event=COMMENT",
                "-f",
                "body=Submitting pending automated review replies.",
            ],
            check=True,
        )
        submitted.append(review_id)
    return submitted


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

    if args.dry_run:
        print(f"[dry-run] Would reply to thread: {args.thread_id}")
        print("-----")
        print(reply_body.rstrip())
        print("-----")
        if args.repo and args.pr_number:
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
    pending_before: set[int] = set()
    login = ""
    if args.repo and args.pr_number:
        login = current_login()
        pending_before = list_pending_review_ids(args.repo, args.pr_number, login)
    result = run_cmd(
        ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"threadId={args.thread_id}", "-F", f"body={reply_body}"],
        check=True,
    )
    sys.stdout.write(result.stdout)
    if args.repo and args.pr_number:
        payload = json.loads(result.stdout)
        reply_url = payload.get("data", {}).get("addPullRequestReviewThreadReply", {}).get("comment", {}).get("url", "")
        pending_after = list_pending_review_ids(args.repo, args.pr_number, login)
        submitted_pending_reviews = submit_pending_reviews(args.repo, args.pr_number, sorted(pending_after))
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
                "pending_reviews_before": sorted(pending_before),
                "pending_reviews_after": sorted(pending_after),
                "submitted_pending_reviews": submitted_pending_reviews,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
