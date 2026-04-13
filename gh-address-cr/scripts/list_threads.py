#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json

from python_common import list_threads


def main() -> int:
    parser = argparse.ArgumentParser(description="List GitHub PR review threads in normalized JSONL form.")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    for row in list_threads(args.repo, args.pr_number):
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
