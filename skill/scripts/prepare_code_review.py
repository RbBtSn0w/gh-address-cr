#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys

from python_common import findings_file, reply_file, loop_artifact_file, workspace_dir


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
        "workspace_dir": str(workspace_dir(args.repo, args.pr_number)),
        "findings_output_path": str(findings_file(args.repo, args.pr_number)),
        "reply_output_path": str(reply_file(args.repo, args.pr_number, "reply.md")),
        "loop_request_path": str(loop_artifact_file(args.repo, args.pr_number, "loop-request.json")),
        "instructions": [
            "Review the PR and emit findings JSON, not a Markdown-only summary.",
            "Each finding must include: title, body, path, line.",
            "Optional fields: severity, category, confidence.",
            "If there are no findings, emit an empty JSON array [].",
            "Do not post to GitHub or mutate repository state.",
            "Write review artifacts into the provided workspace paths, not the project workspace.",
        ],
        "adapter_backend": ("python3 scripts/cli.py code-review-adapter --input -"),
        "review_to_findings_command": (
            f"python3 scripts/cli.py review-to-findings --input - --output "
            f"{findings_file(args.repo, args.pr_number)} {args.repo} {args.pr_number} --workspace "
            f"{workspace_dir(args.repo, args.pr_number)}"
        ),
        "ingest_command": (
            f"python3 scripts/cli.py control-plane {args.mode} code-review "
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
