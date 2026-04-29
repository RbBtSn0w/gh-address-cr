#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json

from python_common import audit_log_file, audit_summary_file, session_file, sha256_of_file, trace_log_file


def load_jsonl(path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def filter_run(rows, run_id: str):
    return [row for row in rows if row.get("run_id") == run_id or row.get("audit_id") == run_id]


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the audit report for a PR session.")
    parser.add_argument("--run-id", default="")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    log_file = audit_log_file(args.repo, args.pr_number)
    trace_file = trace_log_file(args.repo, args.pr_number)
    summary = audit_summary_file(args.repo, args.pr_number)
    session = session_file(args.repo, args.pr_number)

    print("== Audit Report ==")
    print(f"Repo: {args.repo}")
    print(f"PR:   {args.pr_number}")
    if args.run_id:
        print(f"Run: {args.run_id}")
    print(f"Log:  {log_file}")
    print(f"Trace: {trace_file}")
    print(f"Summary: {summary}")
    print(f"Session: {session}")
    print()

    if log_file.exists():
        rows = load_jsonl(log_file)
        if args.run_id:
            rows = filter_run(rows, args.run_id)
            print("== Audit Events For Run ==")
        else:
            rows = rows[-20:]
            print("== Last 20 Audit Events ==")
        if rows:
            for row in rows:
                print(json.dumps(row, sort_keys=True))
        else:
            print("No matching audit events found.")
    else:
        print("No audit log found.")

    print()
    if trace_file.exists():
        rows = load_jsonl(trace_file)
        if args.run_id:
            rows = filter_run(rows, args.run_id)
            print("== Trace Events For Run ==")
        else:
            rows = rows[-40:]
            print("== Last 40 Trace Events ==")
        if rows:
            for row in rows:
                print(json.dumps(row, sort_keys=True))
        else:
            print("No matching trace events found.")
    else:
        print("No trace log found.")

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
