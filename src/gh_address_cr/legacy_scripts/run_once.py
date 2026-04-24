#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json

from python_common import audit_event, previous_snapshot_file, refresh_threads_snapshot, session_engine, session_file, snapshot_file


def unresolved_ids_from_snapshot_text(snapshot_text: str) -> list[str]:
    unresolved_ids = set()
    for line in snapshot_text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not row["isResolved"]:
            unresolved_ids.add(row["id"])
    return sorted(unresolved_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch PR threads, sync the session, and print unresolved work.")
    parser.add_argument("--show-all", action="store_true")
    parser.add_argument("--audit-id", default="default")
    parser.add_argument("repo")
    parser.add_argument("pr_number")
    args = parser.parse_args()

    snapshot = snapshot_file(args.repo, args.pr_number)
    prev_snapshot = previous_snapshot_file(args.repo, args.pr_number)

    audit_event("run_once", "start", args.repo, args.pr_number, args.audit_id, "Starting triage snapshot")

    if snapshot.exists():
        prev_snapshot.write_text(snapshot.read_text(encoding="utf-8"), encoding="utf-8")

    threads, snapshot = refresh_threads_snapshot(args.repo, args.pr_number)

    print("== PR Review Threads ==")
    for row in threads:
        print(json.dumps(row, sort_keys=True))

    session_engine(["init", args.repo, args.pr_number], check=True)
    session_engine(["sync-github", args.repo, args.pr_number, "--scan-id", args.audit_id], input_text=snapshot.read_text(encoding="utf-8"), check=True)

    print()
    title = "== Unresolved Threads (including handled) ==" if args.show_all else "== Unresolved Threads (excluding handled) =="
    print(title)
    list_result = session_engine(
        [
            "list-items",
            args.repo,
            args.pr_number,
            "--item-kind",
            "github_thread",
            "--status",
            "OPEN",
            "--status",
            "STALE",
            *(["--unhandled"] if not args.show_all else []),
        ],
        check=True,
    )
    if list_result.stdout.strip():
        print(list_result.stdout.rstrip())

    unresolved_ids = sorted({row["id"] for row in threads if not row["isResolved"]})
    if prev_snapshot.exists():
        previous = unresolved_ids_from_snapshot_text(prev_snapshot.read_text(encoding="utf-8"))
        newly_appeared = [item_id for item_id in unresolved_ids if item_id not in set(previous)]
    else:
        newly_appeared = []

    print()
    print("== Newly Appeared Unresolved Threads Since Last Snapshot ==")
    if newly_appeared:
        rows_by_id = {row["id"]: row for row in threads}
        for item_id in newly_appeared:
            print(json.dumps(rows_by_id[item_id], sort_keys=True))
    else:
        print("None")

    print()
    print(f"Snapshot saved: {snapshot}")
    print(f"Session state:  {session_file(args.repo, args.pr_number)}")

    audit_event(
        "run_once",
        "ok",
        args.repo,
        args.pr_number,
        args.audit_id,
        "Triage snapshot completed",
        {
            "unresolved_count": len(unresolved_ids),
            "new_unresolved_count": len(newly_appeared),
            "snapshot": str(snapshot),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
