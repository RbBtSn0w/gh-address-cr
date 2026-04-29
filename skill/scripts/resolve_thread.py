#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

from python_common import (
    audit_event,
    github_thread_reply_evidence,
    handled_threads_file,
    gh_write_cmd,
    is_transient_gh_failure,
    run_cmd,
    session_engine,
)


def append_handled(thread_id: str, repo: str, pr_number: str):
    path = handled_threads_file(repo, pr_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set(path.read_text(encoding="utf-8").splitlines()) if path.exists() else set()
    if thread_id not in existing:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{thread_id}\n")


def is_unknown_item_error(stderr: str) -> bool:
    return "Unknown item:" in (stderr or "")


def emit_result(payload: dict, exit_code: int, *, error_message: str | None = None) -> int:
    sys.stdout.write(json.dumps(payload))
    if error_message:
        print(error_message, file=sys.stderr)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve a GitHub PR review thread and sync session state.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", dest="pr_number", default="")
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("thread_id")
    args = parser.parse_args()

    if not args.repo or not args.pr_number:
        raise SystemExit("Error: --repo and --pr are required if gh context is unavailable.")

    if args.dry_run:
        print(f"[dry-run] Would resolve thread: {args.thread_id}")
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
    payload = {
        "action": "resolve_thread",
        "status": "failed",
        "thread_id": args.thread_id,
        "remote_status": "failed",
        "session_status": "skipped",
        "resolved": False,
        "error": None,
    }
    try:
        has_reply_evidence, reply_error = github_thread_reply_evidence(
            args.repo,
            args.pr_number,
            args.thread_id,
            require_tracked=True,
        )
        if not has_reply_evidence:
            payload["status"] = "failed"
            payload["error"] = reply_error
            audit_event(
                "resolve_thread",
                "failed",
                args.repo,
                args.pr_number,
                args.audit_id,
                "Refused to resolve thread without reply evidence",
                {"thread_id": args.thread_id, "error": payload["error"]},
            )
            return emit_result(payload, 1, error_message=payload["error"])

        result = gh_write_cmd(
            ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"threadId={args.thread_id}"],
            check=False,
        )
        if result.returncode != 0:
            payload["status"] = "retryable" if is_transient_gh_failure(result.stderr, result.stdout, result.returncode) else "failed"
            payload["error"] = result.stderr or "resolve failed"
            audit_event(
                "resolve_thread",
                "failed",
                args.repo,
                args.pr_number,
                args.audit_id,
                "Failed to resolve thread",
                {"thread_id": args.thread_id, "error": payload["error"]},
            )
            return emit_result(payload, 1, error_message=payload["error"])

        try:
            resolve_payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            payload["status"] = "failed"
            payload["error"] = "resolve response was not valid JSON"
            audit_event(
                "resolve_thread",
                "failed",
                args.repo,
                args.pr_number,
                args.audit_id,
                "Resolve response was not valid JSON",
                {"thread_id": args.thread_id, "error": payload["error"]},
            )
            return emit_result(payload, 1, error_message=payload["error"])
        resolved = resolve_payload.get("data", {}).get("resolveReviewThread", {}).get("thread", {}).get("isResolved", False)
        payload["remote_status"] = "succeeded"
        payload["resolved"] = bool(resolved)

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
                payload["status"] = "unknown"
                payload["session_status"] = "failed"
                payload["error"] = update.stderr or "session update failed"
                audit_event(
                    "resolve_thread",
                    "partial",
                    args.repo,
                    args.pr_number,
                    args.audit_id,
                    "Resolved thread remotely but session update failed",
                    {"thread_id": args.thread_id, "error": payload["error"]},
                )
                return emit_result(payload, update.returncode or 1, error_message=payload["error"])
            payload["session_status"] = "missing"
        else:
            payload["session_status"] = "succeeded"

        append_handled(args.thread_id, args.repo, args.pr_number)
        payload["status"] = "succeeded"
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
                "session_item_missing": payload["session_status"] == "missing",
            },
        )
        return emit_result(payload, 0)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        payload["status"] = "unknown" if payload["remote_status"] == "succeeded" else "failed"
        payload["session_status"] = "failed"
        payload["error"] = (getattr(exc, "stderr", "") or getattr(exc, "stdout", "") or str(exc)).strip()
        audit_event(
            "resolve_thread",
            "partial" if payload["remote_status"] == "succeeded" else "failed",
            args.repo,
            args.pr_number,
            args.audit_id,
            "Resolve thread command failed",
            {"thread_id": args.thread_id, "error": payload["error"]},
        )
        return emit_result(payload, exc.returncode or 1, error_message=payload["error"])


if __name__ == "__main__":
    raise SystemExit(main())
