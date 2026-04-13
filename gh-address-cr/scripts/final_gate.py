#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

from python_common import audit_event, audit_summary_file, list_threads, session_engine, sha256_of_file, snapshot_file, workspace_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the final PR/session gate.")
    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument("--auto-clean", dest="auto_clean", action="store_true")
    auto_group.add_argument("--no-auto-clean", dest="auto_clean", action="store_false")
    parser.set_defaults(auto_clean=True)
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    audit_event("final_gate", "start", args.repo, args.pr_number, args.audit_id, "Running final freshness gate")

    snapshot = snapshot_file(args.repo, args.pr_number)
    summary = audit_summary_file(args.repo, args.pr_number)
    threads = list_threads(args.repo, args.pr_number)
    snapshot.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in threads), encoding="utf-8")

    session_engine(["init", args.repo, args.pr_number], check=True)
    session_engine(["sync-github", args.repo, args.pr_number, "--scan-id", args.audit_id], input_text=snapshot.read_text(encoding="utf-8"), check=True)
    gate = session_engine(["gate", args.repo, args.pr_number])

    gate_output = gate.stdout
    data = {}
    for line in gate_output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()

    unresolved_count = int(data.get("unresolved_github_threads_count", "0"))
    blocking_count = int(data.get("blocking_items_count", "0"))
    summary_from_engine = data.get("audit_summary")
    summary_hash = data.get("audit_summary_sha256")

    print("== Final Freshness Check ==")
    print(f"Unresolved thread count: {unresolved_count}")

    if gate.returncode != 0:
        failure_reasons = []
        if unresolved_count:
            failure_reasons.append(f"{unresolved_count} unresolved thread(s)")
        if blocking_count:
            failure_reasons.append(f"{blocking_count} blocking item(s)")
        if not failure_reasons:
            failure_reasons.append("gate checks reported failure")
        failure_message = f"Gate failed; {' and '.join(failure_reasons)} remain"
        print()
        print("== Pending Review Table ==")
        items = session_engine(["list-items", args.repo, args.pr_number], check=True)
        for line in items.stdout.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("blocking"):
                print(f"- id={item['item_id']} path={item.get('path') or '-'} line={item.get('line') or '-'} url={item.get('url') or '-'}")
        if summary_from_engine and summary_from_engine != str(summary):
            summary.write_text(Path(summary_from_engine).read_text(encoding="utf-8"), encoding="utf-8")
        if not summary_hash and summary.exists():
            summary_hash = sha256_of_file(summary)
        print(gate_output.rstrip())
        print(f"Audit summary: {summary}")
        print(f"Audit summary sha256: {summary_hash}")
        audit_event(
            "final_gate",
            "failed",
            args.repo,
            args.pr_number,
            args.audit_id,
            failure_message,
            {
                "unresolved_count": unresolved_count,
                "blocking_count": blocking_count,
                "summary_file": str(summary),
                "summary_sha256": summary_hash,
            },
        )
        print("\nGate FAILED: blocking session items remain. Do not send completion summary.", file=sys.stderr)
        return 3

    print("Verified: 0 Unresolved Threads found")
    if summary_from_engine and summary_from_engine != str(summary):
        summary.write_text(Path(summary_from_engine).read_text(encoding="utf-8"), encoding="utf-8")
    if not summary_hash and summary.exists():
        summary_hash = sha256_of_file(summary)
    print(gate_output.rstrip())
    print(f"Audit summary: {summary}")
    print(f"Audit summary sha256: {summary_hash}")
    audit_event(
        "final_gate",
        "ok",
        args.repo,
        args.pr_number,
        args.audit_id,
        "Gate passed with zero unresolved threads",
        {
            "unresolved_count": 0,
            "blocking_count": 0,
            "summary_file": str(summary),
            "summary_sha256": summary_hash,
        },
    )

    if args.auto_clean:
        workspace = workspace_dir(args.repo, args.pr_number)
        audit_event("final_gate", "ok", args.repo, args.pr_number, args.audit_id, "Auto-clean completed after gate pass")
        shutil.rmtree(workspace, ignore_errors=True)
        print(f"Auto-cleaned PR workspace: {workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
