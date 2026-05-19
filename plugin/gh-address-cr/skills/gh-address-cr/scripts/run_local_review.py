#!/usr/bin/env python3
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_ENGINE = SCRIPT_DIR / "session_engine.py"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a local review adapter and ingest findings into the PR session."
    )
    parser.add_argument("--scan-id", default="")
    parser.add_argument("--source", default=None)
    parser.add_argument("--sync", action="store_true", help="Close missing local findings from the same source.")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    parser.add_argument("adapter_cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if not args.adapter_cmd:
        parser.error("missing adapter command")
    if args.sync and not args.source:
        print("`--sync` requires an explicit --source so missing findings stay scoped to one producer.", file=sys.stderr)
        return 2

    scan_id = args.scan_id or ""
    if not SESSION_ENGINE.exists():
        print(f"Missing session engine: {SESSION_ENGINE}", file=sys.stderr)
        return 1

    adapter_result = subprocess.run(args.adapter_cmd, text=True, capture_output=True)
    if adapter_result.returncode != 0:
        sys.stderr.write(adapter_result.stderr)
        return adapter_result.returncode

    subprocess.run(
        [sys.executable, str(SESSION_ENGINE), "init", args.repo, args.pr_number],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    ingest_cmd = [
        sys.executable,
        str(SESSION_ENGINE),
        "ingest-local",
        args.repo,
        args.pr_number,
        "--source",
        args.source or "local-agent:custom",
    ]
    if scan_id:
        ingest_cmd.extend(["--scan-id", scan_id])
    if args.sync:
        ingest_cmd.append("--sync")

    ingest_result = subprocess.run(
        ingest_cmd,
        input=adapter_result.stdout,
        text=True,
        capture_output=True,
    )
    sys.stdout.write(ingest_result.stdout)
    sys.stderr.write(ingest_result.stderr)
    return ingest_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
