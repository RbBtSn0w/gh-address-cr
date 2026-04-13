#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path

from python_common import handled_threads_file, session_engine, state_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark a GitHub thread handled without resolving it.")
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", dest="pr_number", default="")
    parser.add_argument("thread_id")
    args = parser.parse_args()

    if args.repo and args.pr_number:
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

    handled_file = state_dir() / "handled_threads.txt"
    handled_file.parent.mkdir(parents=True, exist_ok=True)
    handled_file.touch(exist_ok=True)
    existing = set(handled_file.read_text(encoding="utf-8").splitlines())
    if args.thread_id not in existing:
        handled_file.write_text(handled_file.read_text(encoding="utf-8") + f"{args.thread_id}\n", encoding="utf-8")
    print(f"Marked handled: {args.thread_id} (scope: global fallback)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
