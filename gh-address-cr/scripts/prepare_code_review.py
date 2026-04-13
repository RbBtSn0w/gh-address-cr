#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit a standard prompt for producer=code-review findings generation."
    )
    parser.add_argument("mode", choices=["local", "mixed"])
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    prompt = {
        "producer": "code-review",
        "mode": args.mode,
        "repo": args.repo,
        "pr_number": args.pr_number,
        "instructions": [
            "Review the PR and emit findings JSON, not a Markdown-only summary.",
            "Each finding must include: title, body, path, line.",
            "Optional fields: severity, category, confidence.",
            "If there are no findings, emit an empty JSON array [].",
            "Do not post to GitHub or mutate repository state.",
        ],
        "adapter_backend": (
            "python3 gh-address-cr/scripts/cli.py code-review-adapter --input -"
        ),
        "ingest_command": (
            f"python3 gh-address-cr/scripts/cli.py control-plane {args.mode} code-review "
            f"--input - {args.repo} {args.pr_number}"
        ),
        "json_contract": [
            {
                "title": "Missing null guard",
                "body": "Potential null dereference.",
                "path": "src/example.py",
                "line": 12,
                "severity": "P2",
                "category": "correctness",
                "confidence": "high",
            }
        ],
    }
    json.dump(prompt, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
