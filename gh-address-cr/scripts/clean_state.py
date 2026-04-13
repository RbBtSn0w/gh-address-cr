#!/usr/bin/env python3
from __future__ import annotations
import argparse
import shutil
from pathlib import Path

from python_common import artifacts_dir, audit_log_file, audit_summary_file, state_dir


def cleanup_pr_state_files(repo: str, pr_number: str) -> None:
    repo_key = repo.replace("/", "__")
    base = state_dir()
    for suffix in [
        f"{repo_key}__pr{pr_number}__session.json",
        f"{repo_key}__pr{pr_number}__threads.jsonl",
        f"{repo_key}__pr{pr_number}__threads.jsonl.prev",
        f"{repo_key}__pr{pr_number}__handled_threads.txt",
        f"{repo_key}__pr{pr_number}__current_unresolved_ids.txt",
        f"{repo_key}__pr{pr_number}__prev_unresolved_ids.txt",
        f"{repo_key}__pr{pr_number}__new_unresolved_ids.txt",
    ]:
        path = base / suffix
        if path.exists():
            path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean gh-address-cr session state.")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", dest="pr_number", default="")
    parser.add_argument("--clean-tmp", action="store_true")
    return parser.parse_args()


def remove_tmp_files() -> None:
    patterns = ("/tmp/gh-cr-reply*.md", "/tmp/reply-fixed-*.md")
    found = False
    for pattern in patterns:
        matches = list(Path("/").glob(pattern.lstrip("/")))
        if not matches:
            continue
        found = True
        for match in matches:
            match.unlink(missing_ok=True)
        print(f"Removed temp files: {pattern}")
    if not found:
        print("No matching temp reply files found in /tmp.")


def main() -> int:
    args = parse_args()
    if args.all and (args.repo or args.pr_number):
        raise SystemExit("Unknown option combination: --all cannot be used with --repo/--pr")
    if (args.repo or args.pr_number) and not (args.repo and args.pr_number):
        raise SystemExit("Usage: clean_state.py [--repo <owner/repo> --pr <number> | --all] [--clean-tmp]")

    base = state_dir()
    if args.all:
        if base.exists():
            shutil.rmtree(base)
            print(f"Removed all state dir: {base}")
        else:
            print(f"State dir not found: {base}")
    elif args.repo and args.pr_number:
        cleanup_pr_state_files(args.repo, args.pr_number)
        audit_log_file(args.repo, args.pr_number).unlink(missing_ok=True)
        audit_summary_file(args.repo, args.pr_number).unlink(missing_ok=True)
        shutil.rmtree(artifacts_dir(args.repo, args.pr_number), ignore_errors=True)
        print(f"Removed PR state for: {args.repo} #{args.pr_number}")
    else:
        if base.exists():
            shutil.rmtree(base)
            print(f"Removed all state dir (no --repo/--pr provided): {base}")
        else:
            print(f"State dir not found: {base}")

    if args.clean_tmp:
        remove_tmp_files()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
