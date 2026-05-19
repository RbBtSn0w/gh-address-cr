#!/usr/bin/env python3
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
RESOLVE_THREAD = SCRIPT_DIR / "resolve_thread.py"
APPROVED_RE = re.compile(r"^\s*APPROVED\s+([^\s]+)\s*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve a batch of approved GitHub review threads.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr", dest="pr_number", default="")
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("approved_threads_file")
    return parser.parse_args()


def iter_approved_thread_ids(path: Path):
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        match = APPROVED_RE.match(raw_line)
        if not match:
            raise SystemExit(f"Invalid line in approved list: '{raw_line}'\nExpected format: APPROVED <thread_id>")
        yield match.group(1)


def main() -> int:
    args = parse_args()

    if not args.repo or not args.pr_number:
        raise SystemExit("Error: --repo and --pr are required if gh context is unavailable.")

    approved_path = Path(args.approved_threads_file)
    if not approved_path.is_file():
        raise SystemExit(f"Approved thread file not found: {approved_path}")
    if not args.dry_run and not args.yes:
        raise SystemExit("Refusing destructive bulk action without --yes (or use --dry-run).")

    for thread_id in iter_approved_thread_ids(approved_path):
        cmd = [sys.executable, str(RESOLVE_THREAD)]
        if args.dry_run:
            cmd.append("--dry-run")
        cmd.extend(["--repo", args.repo, "--pr", args.pr_number, "--audit-id", args.audit_id])
        cmd.append(thread_id)
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode != 0:
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
