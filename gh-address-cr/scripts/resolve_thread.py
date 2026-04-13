#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from python_common import audit_event, handled_threads_file, run_cmd, session_engine, state_dir


def append_handled(thread_id: str, repo: str | None = None, pr_number: str | None = None):
    if repo and pr_number:
        path = handled_threads_file(repo, pr_number)
    else:
        path = state_dir() / "handled_threads.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set(path.read_text(encoding="utf-8").splitlines()) if path.exists() else set()
    if thread_id not in existing:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{thread_id}\n")


def is_unknown_item_error(stderr: str) -> bool:
    return "Unknown item:" in (stderr or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve a GitHub PR review thread and sync session state.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", dest="pr_number", default="")
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("thread_id")
    args = parser.parse_args()

    if args.dry_run:
        print(f"[dry-run] Would resolve thread: {args.thread_id}")
        if args.repo and args.pr_number:
            audit_event(
                "resolve_thread",
                "dry-run",
                args.repo,
                args.pr_number,
                args.audit_id,
                "Previewed thread resolve",
                {"thread_id": args.thread_id},
            )
        return 0

    query = "mutation($threadId:ID!){ resolveReviewThread(input:{threadId:$threadId}) { thread { id isResolved } } }"
    result = run_cmd(
        ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"threadId={args.thread_id}"],
        check=True,
    )
    sys.stdout.write(result.stdout)

    if args.repo and args.pr_number:
        session_engine(["init", args.repo, args.pr_number], check=True)
        update = run_cmd(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "session_engine.py"),
                "update-item",
                args.repo,
                args.pr_number,
                f"github-thread:{args.thread_id}",
                "CLOSED",
                "--note",
                "Resolved on GitHub.",
                "--actor",
                "resolve_thread",
                "--handled",
            ]
        )
        if update.returncode != 0:
            if not is_unknown_item_error(update.stderr):
                sys.stderr.write(update.stderr)
                return update.returncode
        append_handled(args.thread_id, args.repo, args.pr_number)
        payload = json.loads(result.stdout)
        resolved = payload.get("data", {}).get("resolveReviewThread", {}).get("thread", {}).get("isResolved", False)
        audit_event(
            "resolve_thread",
            "ok",
            args.repo,
            args.pr_number,
            args.audit_id,
            "Resolved thread",
            {
                "thread_id": args.thread_id,
                "is_resolved": resolved,
                "session_item_missing": bool(update.returncode != 0 and is_unknown_item_error(update.stderr)),
            },
        )
    else:
        append_handled(args.thread_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
