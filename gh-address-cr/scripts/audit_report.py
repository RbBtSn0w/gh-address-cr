#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json

from python_common import audit_log_file, audit_summary_file, session_file, sha256_of_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the audit report for a PR session.")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    log_file = audit_log_file(args.repo, args.pr_number)
    summary = audit_summary_file(args.repo, args.pr_number)
    session = session_file(args.repo, args.pr_number)

    print("== Audit Report ==")
    print(f"Repo: {args.repo}")
    print(f"PR:   {args.pr_number}")
    print(f"Log:  {log_file}")
    print(f"Summary: {summary}")
    print(f"Session: {session}")
    print()

    if log_file.exists():
        print("== Last 20 Audit Events ==")
        for line in log_file.read_text(encoding="utf-8").splitlines()[-20:]:
            if line.strip():
                print(json.dumps(json.loads(line), sort_keys=True))
    else:
        print("No audit log found.")

    print()
    if session.exists():
        print("== Session Metrics ==")
        payload = json.loads(session.read_text(encoding="utf-8"))
        for key, value in payload.get("metrics", {}).items():
            print(f"{key}={value}")
    else:
        print("No session state found.")

    print()
    if summary.exists():
        print("== Audit Summary SHA256 ==")
        print(f"{sha256_of_file(summary)}  {summary}")
    else:
        print("No audit summary found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
