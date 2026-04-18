#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

from python_common import (
    audit_event,
    audit_summary_file,
    copy_threads_snapshot,
    github_viewer_login,
    list_pending_review_ids,
    reserve_archive_dir,
    refresh_threads_snapshot,
    session_engine,
    sha256_of_file,
    snapshot_file,
    workspace_dir,
)


def metric_count(data: dict[str, str], key: str) -> int:
    return int(data.get(key, "0"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the final PR/session gate.")
    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument("--auto-clean", dest="auto_clean", action="store_true")
    auto_group.add_argument("--no-auto-clean", dest="auto_clean", action="store_false")
    parser.set_defaults(auto_clean=True)
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("--snapshot", default="", help="Reuse an existing PR threads snapshot instead of fetching GitHub again.")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    audit_event("final_gate", "start", args.repo, args.pr_number, args.audit_id, "Running final freshness gate")

    snapshot = snapshot_file(args.repo, args.pr_number)
    summary = audit_summary_file(args.repo, args.pr_number)
    if args.snapshot:
        snapshot_source = Path(args.snapshot)
        if not snapshot_source.exists():
            print(f"Snapshot file not found: {snapshot_source}", file=sys.stderr)
            return 2
        snapshot = copy_threads_snapshot(args.repo, args.pr_number, snapshot_source)
    else:
        _, snapshot = refresh_threads_snapshot(args.repo, args.pr_number)

    session_engine(["init", args.repo, args.pr_number], check=True)
    session_engine(["sync-github", args.repo, args.pr_number, "--scan-id", args.audit_id], input_text=snapshot.read_text(encoding="utf-8"), check=True)
    gate = session_engine(["gate", args.repo, args.pr_number])

    gate_output = gate.stdout
    data = {}
    for line in gate_output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()

    unresolved_count = metric_count(data, "unresolved_github_threads_count")
    blocking_count = metric_count(data, "blocking_items_count")
    summary_from_engine = data.get("audit_summary")
    summary_hash = data.get("audit_summary_sha256")
    login = github_viewer_login()
    pending_review_ids = sorted(list_pending_review_ids(args.repo, args.pr_number, login))
    pending_review_count = len(pending_review_ids)

    print("== Final Freshness Check ==")
    print(f"Unresolved thread count: {unresolved_count}")
    print(f"Pending review count: {pending_review_count}")

    if gate.returncode != 0 or pending_review_count:
        failure_reasons = []
        if unresolved_count:
            failure_reasons.append(f"{unresolved_count} unresolved thread(s)")
        if blocking_count:
            failure_reasons.append(f"{blocking_count} blocking item(s)")
        if pending_review_count:
            failure_reasons.append(f"{pending_review_count} pending review(s)")
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
        print()
        print("== Machine Gate Diagnostics ==")
        print(gate_output.rstrip())
        if pending_review_ids:
            print(f"Pending review ids: {', '.join(pending_review_ids)}")
        print(f"Audit summary file: {summary}")
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
                    "pending_review_count": pending_review_count,
                    "pending_review_ids": pending_review_ids,
                    "summary_file": str(summary),
                    "summary_sha256": summary_hash,
                },
        )
        print(f"\nGate FAILED: {failure_message}. Do not send completion summary.", file=sys.stderr)
        return 3

    print()
    print("== Gate Result ==")
    print("Verified: 0 Unresolved Threads found")
    print("Verified: 0 Pending Reviews found")
    print(f"Session blocking items: {blocking_count}")
    if summary_from_engine and summary_from_engine != str(summary):
        summary.write_text(Path(summary_from_engine).read_text(encoding="utf-8"), encoding="utf-8")
    if not summary_hash and summary.exists():
        summary_hash = sha256_of_file(summary)
    print()
    print("== Machine Gate Diagnostics ==")
    print(gate_output.rstrip())
    print(f"Audit summary file: {summary}")
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
            "pending_review_count": 0,
            "summary_file": str(summary),
            "summary_sha256": summary_hash,
        },
    )

    if args.auto_clean:
        workspace = workspace_dir(args.repo, args.pr_number)
        archive_target = reserve_archive_dir(args.repo, args.pr_number, args.audit_id or "final-gate")
        audit_event(
            "final_gate",
            "ok",
            args.repo,
            args.pr_number,
            args.audit_id,
            "Archived PR workspace before auto-clean",
            {"archive_dir": str(archive_target)},
        )
        shutil.copytree(workspace, archive_target)
        shutil.rmtree(workspace, ignore_errors=True)
        print(f"Archived PR workspace: {archive_target}")
        print(f"Auto-cleaned PR workspace: {workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
