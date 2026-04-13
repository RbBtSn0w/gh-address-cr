#!/usr/bin/env python3
from __future__ import annotations
import argparse
import shutil

from python_common import state_dir, normalize_repo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean gh-address-cr session state.")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", dest="pr_number", default="")
    parser.add_argument("--clean-tmp", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.all and (args.repo or args.pr_number):
        raise SystemExit("Unknown option combination: --all cannot be used with --repo/--pr")
    if (args.repo or args.pr_number) and not (args.repo and args.pr_number):
        raise SystemExit("Usage: clean_state.py [--repo <owner/repo> --pr <number> | --all]")

    base = state_dir()
    if args.all:
        if base.exists():
            shutil.rmtree(base)
            print(f"Removed all state dir: {base}")
        else:
            print(f"State dir not found: {base}")
    elif args.repo and args.pr_number:
        workspace = state_dir() / normalize_repo(args.repo) / f"pr-{args.pr_number}"
        shutil.rmtree(workspace, ignore_errors=True)
        print(f"Removed PR workspace for: {args.repo} #{args.pr_number}")
    else:
        if base.exists():
            shutil.rmtree(base)
            print(f"Removed all state dir (no --repo/--pr provided): {base}")
        else:
            print(f"State dir not found: {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
