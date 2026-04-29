#!/usr/bin/env python3
from __future__ import annotations
import argparse

from python_common import handled_threads_file, session_engine


def split_item_id(item_id: str) -> tuple[str, str]:
    if item_id.startswith("local-finding:"):
        return "local_finding", item_id
    if item_id.startswith("github-thread:"):
        return "github_thread", item_id
    return "github_thread", f"github-thread:{item_id}"


def default_note(item_kind: str, resolution: str) -> str:
    if item_kind == "local_finding":
        return {
            "fix": "Resolved local finding.",
            "clarify": "Clarified local finding.",
            "defer": "Deferred local finding.",
        }[resolution]
    return "Marked handled without resolving."


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark a GitHub thread or local finding handled.")
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", dest="pr_number", default="")
    parser.add_argument("--res", "--resolution", dest="resolution", choices=["fix", "clarify", "defer"], default="fix")
    parser.add_argument("--note", default="")
    parser.add_argument("item_id")
    args = parser.parse_args()

    if not args.repo or not args.pr_number:
        raise SystemExit("Error: --repo and --pr are required if gh context is unavailable.")

    session_engine(["init", args.repo, args.pr_number], check=True)
    item_kind, normalized_item_id = split_item_id(args.item_id)
    note = args.note or default_note(item_kind, args.resolution)

    if item_kind == "local_finding":
        session_engine(
            [
                "resolve-local-item",
                args.repo,
                args.pr_number,
                normalized_item_id,
                args.resolution,
                "--note",
                note,
                "--actor",
                "mark_handled",
            ],
            check=True,
        )
        print(f"Resolved local item: {normalized_item_id} -> {args.resolution} (scope: {args.repo}#{args.pr_number})")
        return 0

    thread_id = normalized_item_id.removeprefix("github-thread:")
    session_engine(
        [
            "mark-handled",
            args.repo,
            args.pr_number,
            normalized_item_id,
            "--note",
            note,
            "--actor",
            "mark_handled",
        ],
        check=True,
    )
    handled_file = handled_threads_file(args.repo, args.pr_number)
    handled_file.parent.mkdir(parents=True, exist_ok=True)
    handled_file.touch(exist_ok=True)
    content = handled_file.read_text(encoding="utf-8")
    existing = set(content.splitlines()) if content else set()
    if thread_id not in existing:
        handled_file.write_text(content + f"{thread_id}\n", encoding="utf-8")
    print(f"Marked handled: {thread_id} (scope: {args.repo}#{args.pr_number})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
