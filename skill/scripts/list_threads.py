#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json

def bootstrap_runtime_path() -> None:
    import os
    import sys
    from pathlib import Path
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[1]
    src_root = repo_root / "src"
    if src_root.is_dir():
        sys.path.insert(0, str(src_root))
    os.environ.setdefault("GH_ADDRESS_CR_COMPAT_SCRIPT_DIR", str(script_dir))


bootstrap_runtime_path()

from gh_address_cr.github.client import GitHubClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="List GitHub PR review threads in normalized JSONL form.")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    for row in GitHubClient().list_threads(args.repo, args.pr_number):
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
