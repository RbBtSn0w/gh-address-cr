#!/usr/bin/env python3
from __future__ import annotations
import argparse
import subprocess
import json

from python_common import handled_threads_file, session_engine


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark a GitHub thread handled without resolving it.")
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", dest="pr_number", default="")
    parser.add_argument("thread_id")
    args = parser.parse_args()

    if not args.repo:
        res = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner"], capture_output=True, text=True)
        if res.returncode == 0:
            args.repo = json.loads(res.stdout).get("nameWithOwner", "")
    if not args.pr_number:
        res = subprocess.run(["gh", "pr", "view", "--json", "number"], capture_output=True, text=True)
        if res.returncode == 0:
            args.pr_number = str(json.loads(res.stdout).get("number", ""))

    if not args.repo or not args.pr_number:
        raise SystemExit("Error: --repo and --pr are required if gh context is unavailable.")

    session_engine(["init", args.repo, args.pr_number], check=True)
    session_engine(
        [
            "mark-handled",
            args.repo,
            args.pr_number,
            f"github-thread:{args.thread_id}",
            "--note",
            "Marked handled without resolving.",
            "--actor",
            "mark_handled",
        ],
        check=True,
    )
    handled_file = handled_threads_file(args.repo, args.pr_number)
    handled_file.parent.mkdir(parents=True, exist_ok=True)
    handled_file.touch(exist_ok=True)
    existing = set(handled_file.read_text(encoding="utf-8").splitlines()) if handled_file.exists() else set()
    if args.thread_id not in existing:
        handled_file.write_text((handled_file.read_text(encoding="utf-8") if handled_file.exists() else "") + f"{args.thread_id}\n", encoding="utf-8")
    print(f"Marked handled: {args.thread_id} (scope: {args.repo}#{args.pr_number})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
