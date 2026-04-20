#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import sys
import shlex
from pathlib import Path
import subprocess

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit an action to a blocked loop and resume.")
    parser.add_argument("loop_request", help="Path to the loop-request JSON artifact.")
    parser.add_argument("--resolution", choices=["fix", "clarify", "defer"], required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--reply-markdown")
    parser.add_argument("--commit-hash")
    parser.add_argument("--files")
    parser.add_argument("--severity", choices=["P1", "P2", "P3"])
    parser.add_argument("--why")
    parser.add_argument("--test-command")
    parser.add_argument("--test-result")
    parser.add_argument("--validation-cmd", action="append", default=[])
    parser.add_argument("--human", action="store_true", help="Emit human-oriented text instead of machine summary.")
    parser.add_argument("--machine", action="store_true", help="Compatibility alias.")
    parser.add_argument("resume_cmd", nargs=argparse.REMAINDER, help="Original command to resume (e.g. python3 scripts/cli.py review owner/repo 1)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    req_path = Path(args.loop_request)
    if not req_path.is_file():
        print(f"Error: loop-request file not found: {req_path}", file=sys.stderr)
        return 2

    try:
        req = json.loads(req_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"Error: invalid JSON in {req_path}", file=sys.stderr)
        return 2

    repo = req.get("repo")
    pr_number = req.get("pr_number")
    item = req.get("item")

    if not repo or not pr_number or not item:
        print("Error: loop-request missing repo, pr_number, or item", file=sys.stderr)
        return 2

    item_kind = item.get("item_kind")

    # Validation: fix for GitHub thread requires fix_reply details
    if args.resolution == "fix" and item_kind == "github_thread":
        if not args.commit_hash or not args.files:
            print("Error: --resolution fix for github_thread requires --commit-hash and --files", file=sys.stderr)
            return 2
    # Validation: clarify/defer for GitHub thread requires reply_markdown
    if args.resolution in {"clarify", "defer"} and item_kind == "github_thread":
        if not args.reply_markdown:
            print(f"Error: --resolution {args.resolution} for github_thread requires --reply-markdown", file=sys.stderr)
            return 2

    action = {
        "resolution": args.resolution,
        "note": args.note,
    }
    if args.reply_markdown:
        action["reply_markdown"] = args.reply_markdown

    if any([args.commit_hash, args.files, args.severity, args.why, args.test_command, args.test_result]):
        action["fix_reply"] = {
            "commit_hash": args.commit_hash,
            "files": args.files,
            "severity": args.severity,
            "why": args.why,
            "test_command": args.test_command,
            "test_result": args.test_result,
        }

    if args.validation_cmd:
        action["validation_commands"] = args.validation_cmd

    safe_item_id = item.get("item_id", "unknown").replace("/", "_").replace(":", "_")
    output_path = req_path.parent / f"fixer-payload-{safe_item_id}.json"

    output_path.write_text(json.dumps(action, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    script_path = req_path.parent / f"fixer-{safe_item_id}.sh"
    script_path.write_text(f"#!/bin/sh\ncat {shlex.quote(str(output_path))}\n", encoding="utf-8")
    os.chmod(script_path, 0o755)

    cmd = list(args.resume_cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]

    if cmd:
        cmd.extend(["--fixer-cmd", str(script_path)])
        print(f"Resuming loop with submitted action '{args.resolution}'...")
        result = subprocess.run(cmd)
        return result.returncode

    print(f"Action '{args.resolution}' formulated for {item.get('item_id')}.")
    print("To resume the PR session, run your original loop command and append:")
    print(f"  --fixer-cmd \"{script_path}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
