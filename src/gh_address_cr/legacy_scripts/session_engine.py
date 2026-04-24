#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingest_findings import normalize_finding

from python_common import (
    audit_event as write_audit_event,
    audit_log_file,
    audit_summary_file,
    item_has_reply_evidence,
    session_file,
    state_dir,
)


SCHEMA_VERSION = 1
DEFAULT_CLAIM_MINUTES = 30
LOOP_WARNING_THRESHOLD = 3
BLOCKING_STATUSES = {"OPEN", "CLAIMED", "ACCEPTED", "FIX_IN_PROGRESS", "FIXED", "PUBLISHED", "STALE"}
NON_BLOCKING_STATUSES = {"VERIFIED", "CLARIFIED", "DEFERRED", "CLOSED", "DROPPED"}
VALID_STATUSES = BLOCKING_STATUSES | NON_BLOCKING_STATUSES
GITHUB_TERMINAL_STATUSES = {"CLOSED", "DROPPED"}
STATUSES_REQUIRING_NOTE = {"ACCEPTED", "FIXED", "VERIFIED", "CLARIFIED", "DEFERRED", "CLOSED", "PUBLISHED"}
ALLOWED_TRANSITIONS = {
    "OPEN": {"CLAIMED", "ACCEPTED", "CLARIFIED", "DEFERRED", "PUBLISHED", "CLOSED", "DROPPED", "STALE"},
    "CLAIMED": {"ACCEPTED", "FIX_IN_PROGRESS", "CLARIFIED", "DEFERRED", "PUBLISHED", "CLOSED", "DROPPED", "STALE"},
    "ACCEPTED": {"FIX_IN_PROGRESS", "FIXED", "CLARIFIED", "DEFERRED", "PUBLISHED", "CLOSED", "DROPPED", "STALE"},
    "FIX_IN_PROGRESS": {"FIXED", "CLARIFIED", "DEFERRED", "CLOSED", "DROPPED", "STALE"},
    "FIXED": {"VERIFIED", "CLOSED", "STALE"},
    "VERIFIED": {"CLOSED", "STALE"},
    "CLARIFIED": {"OPEN", "CLOSED", "STALE"},
    "DEFERRED": {"OPEN", "CLOSED", "STALE"},
    "PUBLISHED": {"CLAIMED", "ACCEPTED", "FIX_IN_PROGRESS", "FIXED", "VERIFIED", "CLOSED", "STALE"},
    "CLOSED": {"OPEN", "STALE"},
    "DROPPED": {"OPEN", "STALE"},
    "STALE": {"OPEN", "CLAIMED", "ACCEPTED", "CLOSED"},
}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_state_dir() -> Path:
    path = state_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_path(repo: str, pr_number: str) -> Path:
    ensure_state_dir()
    return session_file(repo, pr_number)


def audit_log_path(repo: str, pr_number: str) -> Path:
    ensure_state_dir()
    return audit_log_file(repo, pr_number)


def summary_path(repo: str, pr_number: str) -> Path:
    ensure_state_dir()
    return audit_summary_file(repo, pr_number)


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def append_audit_event(
    repo: str,
    pr_number: str,
    action: str,
    status: str,
    message: str,
    details=None,
    *,
    run_id: str | None = None,
):
    write_audit_event(
        action,
        status,
        repo,
        pr_number,
        audit_id=run_id,
        message=message,
        details=details,
    )


def default_session(repo: str, pr_number: str) -> dict:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": f"{repo}#{pr_number}",
        "repo": repo,
        "pr_number": pr_number,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "current_scan_id": None,
        "metrics": {
            "blocking_items_count": 0,
            "open_local_findings_count": 0,
            "unresolved_github_threads_count": 0,
            "needs_human_items_count": 0,
        },
        "loop_state": {
            "run_id": None,
            "status": "IDLE",
            "iteration": 0,
            "max_iterations": 0,
            "current_item_id": None,
            "last_error": "",
            "last_started_at": None,
            "last_completed_at": None,
        },
        "handoff": {
            "last_consumed_sha256": None,
        },
        "items": {},
        "history": [],
    }


def ensure_loop_state(session: dict):
    loop_state = session.setdefault("loop_state", {})
    loop_state.setdefault("run_id", None)
    loop_state.setdefault("status", "IDLE")
    loop_state.setdefault("iteration", 0)
    loop_state.setdefault("max_iterations", 0)
    loop_state.setdefault("current_item_id", None)
    loop_state.setdefault("last_error", "")
    loop_state.setdefault("last_started_at", None)
    loop_state.setdefault("last_completed_at", None)


def ensure_handoff_state(session: dict):
    handoff = session.setdefault("handoff", {})
    handoff.setdefault("last_consumed_sha256", None)


def current_run_id(session: dict, explicit_run_id: str | None = None) -> str | None:
    if explicit_run_id:
        return explicit_run_id
    loop_state = session.get("loop_state")
    if isinstance(loop_state, dict):
        run_id = loop_state.get("run_id")
        if run_id:
            return run_id
    scan_id = session.get("current_scan_id")
    if isinstance(scan_id, str) and scan_id:
        return scan_id
    return None


def ensure_item_runtime_fields(item: dict):
    item.setdefault("auto_attempt_count", 0)
    item.setdefault("last_auto_action", None)
    item.setdefault("last_auto_failure", None)
    item.setdefault("needs_human", False)
    item.setdefault("reply_posted", False)
    item.setdefault("reply_url", None)
    item.setdefault("created_run_id", None)
    item.setdefault("handled_run_id", None)


def load_session(repo: str, pr_number: str) -> dict:
    path = session_path(repo, pr_number)
    if not path.exists():
        raise SystemExit(f"Session not found: {path}. Run `init` first.")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"Unsupported session schema version: {payload.get('schema_version')}")
    ensure_loop_state(payload)
    ensure_handoff_state(payload)
    for item in payload.get("items", {}).values():
        ensure_item_runtime_fields(item)
    return payload


def save_session(session: dict):
    session["updated_at"] = utc_now()
    recalc_metrics(session)
    write_json_atomic(session_path(session["repo"], session["pr_number"]), session)


def recalc_metrics(session: dict):
    items = list(session["items"].values())
    session["metrics"] = {
        "blocking_items_count": sum(1 for item in items if item.get("blocking")),
        "open_local_findings_count": sum(
            1 for item in items if item["item_kind"] == "local_finding" and item.get("blocking")
        ),
        "unresolved_github_threads_count": sum(
            1
            for item in items
            if item["item_kind"] == "github_thread" and item.get("status") not in GITHUB_TERMINAL_STATUSES
        ),
        "needs_human_items_count": sum(1 for item in items if item.get("needs_human")),
    }


def blocking_for_status(status: str) -> bool:
    return status in BLOCKING_STATUSES


def set_handled_state(
    item: dict,
    handled: bool,
    *,
    run_id: str | None,
    now: str | None = None,
    preserve_existing: bool = False,
):
    item["handled"] = handled
    if handled:
        if preserve_existing and item.get("handled_at"):
            return
        item["handled_at"] = now or utc_now()
        item["handled_run_id"] = run_id
        return
    item["handled_at"] = None
    item["handled_run_id"] = None


def gate_progress_counts(session: dict, blocking: list[dict], unresolved_threads: list[dict]) -> dict:
    items = list(session["items"].values())
    github_items = [item for item in items if item["item_kind"] == "github_thread"]
    local_items = [item for item in items if item["item_kind"] == "local_finding"]
    missing_reply_items = [
        item for item in github_items if item["status"] in GITHUB_TERMINAL_STATUSES and not item_has_reply_evidence(item)
    ]
    run_id = current_run_id(session)
    return {
        "tracked_items_count": len(items),
        "handled_items_count": sum(1 for item in items if item.get("handled")),
        "github_threads_total_count": len(github_items),
        "github_threads_handled_count": len(github_items) - len(unresolved_threads),
        "github_threads_new_count": sum(1 for item in github_items if run_id and item.get("created_run_id") == run_id),
        "github_threads_handled_this_run_count": sum(
            1 for item in github_items if run_id and item.get("handled") and item.get("handled_run_id") == run_id
        ),
        "github_threads_unresolved_count": len(unresolved_threads),
        "github_threads_missing_reply_count": len(missing_reply_items),
        "local_findings_total_count": len(local_items),
        "local_findings_handled_count": sum(1 for item in local_items if item.get("handled")),
        "local_findings_new_count": sum(1 for item in local_items if run_id and item.get("created_run_id") == run_id),
        "local_findings_handled_this_run_count": sum(
            1 for item in local_items if run_id and item.get("handled") and item.get("handled_run_id") == run_id
        ),
        "local_findings_unresolved_count": sum(1 for item in local_items if item.get("blocking")),
        "local_findings_blocking_count": sum(1 for item in local_items if item.get("blocking")),
        "blocking_items_count": len(blocking),
    }


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def fingerprint_finding(finding: dict) -> str:
    stable = "|".join(
        [
            finding.get("path", ""),
            str(finding.get("start_line") or finding.get("line") or ""),
            str(finding.get("end_line") or ""),
            normalize_text(finding.get("category", "")),
            normalize_text(finding.get("title", "")),
            normalize_text(finding.get("body", "")),
        ]
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def local_finding_item_id(source: str, finding: dict) -> str:
    stable = json.dumps({"source": source, "fingerprint": fingerprint_finding(finding)}, sort_keys=True, separators=(",", ":"))
    return f"local-finding:{hashlib.sha256(stable.encode('utf-8')).hexdigest()[:16]}"


def legacy_local_finding_item_id(finding: dict) -> str:
    return f"local-finding:{fingerprint_finding(finding)}"


def history_event(event: str, note: str = "", actor: str = "system") -> dict:
    return {"ts": utc_now(), "event": event, "note": note, "actor": actor}


def clear_claim(item: dict):
    item["claimed_by"] = None
    item["claimed_at"] = None
    item["lease_expires_at"] = None


def read_records_from_stdin() -> list[dict]:
    raw = sys.stdin.read().strip()
    if not raw:
        return []
    if raw.startswith("["):
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise SystemExit("Expected a JSON array.")
        return payload
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def upsert_github_thread(session: dict, row: dict) -> tuple[str, bool]:
    item_id = f"github-thread:{row['id']}"
    now = utc_now()
    run_id = current_run_id(session)
    resolved = bool(row.get("isResolved"))
    existing = session["items"].get(item_id)
    existing_status = existing.get("status") if existing else None
    if resolved:
        status = "CLOSED"
    elif bool(row.get("isOutdated")):
        status = "STALE"
    elif existing_status in {"DROPPED", "STALE"}:
        status = existing_status
    else:
        status = "OPEN"
    reopened = bool(existing) and existing_status in GITHUB_TERMINAL_STATUSES and status == "OPEN"
    viewer_reply_checked = row.get("viewer_reply_checked")
    viewer_reply_known = bool(viewer_reply_checked) if isinstance(viewer_reply_checked, bool) else any(
        key in row for key in ("viewer_replied", "viewer_reply_url")
    )
    if reopened:
        reply_posted = False
        reply_url = None
    elif viewer_reply_known:
        reply_posted = bool(row.get("viewer_replied"))
        reply_url = row.get("viewer_reply_url") if reply_posted else None
    else:
        reply_posted = existing.get("reply_posted", False) if existing else False
        reply_url = existing.get("reply_url") if existing else None
    payload = {
        "item_id": item_id,
        "item_kind": "github_thread",
        "source": "github",
        "origin_ref": row["id"],
        "path": row.get("path"),
        "line": row.get("line"),
        "start_line": row.get("start_line"),
        "end_line": row.get("end_line"),
        "title": row.get("title") or "GitHub review thread",
        "body": row.get("body"),
        "severity": row.get("severity") or "P2",
        "confidence": row.get("confidence"),
        "category": row.get("category") or "review-thread",
        "status": status,
        "decision": None,
        "blocking": blocking_for_status(status),
        "handled": False,
        "handled_at": existing.get("handled_at") if existing else None,
        "handled_run_id": existing.get("handled_run_id") if existing else None,
        "resolution_note": existing.get("resolution_note") if existing else None,
        "published": True,
        "published_ref": row.get("url"),
        "url": row.get("url"),
        "first_url": row.get("first_url"),
        "latest_url": row.get("latest_url"),
        "is_outdated": bool(row.get("isOutdated")),
        "scan_id": session.get("current_scan_id"),
        "introduced_in_sha": row.get("introduced_in_sha"),
        "last_seen_in_sha": row.get("last_seen_in_sha"),
        "claimed_by": existing.get("claimed_by") if existing else None,
        "claimed_at": existing.get("claimed_at") if existing else None,
        "lease_expires_at": existing.get("lease_expires_at") if existing else None,
        "repeat_count": existing.get("repeat_count", 0) if existing else 0,
        "reopen_count": existing.get("reopen_count", 0) if existing else 0,
        "evidence": existing.get("evidence", []) if existing else [],
        "history": existing.get("history", []) if existing else [],
        "auto_attempt_count": existing.get("auto_attempt_count", 0) if existing else 0,
        "last_auto_action": existing.get("last_auto_action") if existing else None,
        "last_auto_failure": existing.get("last_auto_failure") if existing else None,
        "needs_human": False if reopened else (existing.get("needs_human", False) if existing else False),
        "reply_posted": reply_posted,
        "reply_url": reply_url,
        "created_at": existing.get("created_at") if existing else now,
        "created_run_id": existing.get("created_run_id") if existing else run_id,
        "updated_at": now,
    }
    if reopened:
        set_handled_state(payload, False, run_id=None)
    elif resolved:
        set_handled_state(
            payload,
            True,
            run_id=run_id,
            now=now,
            preserve_existing=bool(existing and existing.get("handled")),
        )
    else:
        set_handled_state(payload, False, run_id=None)
    created = existing is None
    if created:
        payload["history"].append(history_event("created", "Imported from GitHub"))
    else:
        payload["history"].append(history_event("synced", "Refreshed from GitHub"))
        if reopened:
            payload["reopen_count"] = payload.get("reopen_count", 0) + 1
            payload["history"].append(history_event("reopened", "Thread reopened on GitHub"))
    session["items"][item_id] = payload
    return item_id, created


def add_local_finding(session: dict, finding: dict, source: str) -> tuple[str, bool]:
    fingerprint = fingerprint_finding(finding)
    item_id = local_finding_item_id(source, finding)
    now = utc_now()
    run_id = current_run_id(session)
    existing = session["items"].get(item_id)
    if existing is None:
        legacy_item_id = legacy_local_finding_item_id(finding)
        legacy_item = session["items"].get(legacy_item_id)
        if legacy_item and legacy_item["item_kind"] == "local_finding" and legacy_item.get("source") == source:
            legacy_item["item_id"] = item_id
            legacy_item["history"].append(history_event("migrated", "Migrated local finding to source-scoped item id"))
            session["items"][item_id] = legacy_item
            del session["items"][legacy_item_id]
            existing = legacy_item
    if existing:
        existing["last_seen_in_sha"] = finding.get("head_sha") or existing.get("last_seen_in_sha")
        existing["scan_id"] = session.get("current_scan_id")
        existing["updated_at"] = now
        existing["repeat_count"] = existing.get("repeat_count", 0) + 1
        if existing.get("status") != "OPEN":
            existing["status"] = "OPEN"
            existing["blocking"] = True
            set_handled_state(existing, False, run_id=None)
            existing["needs_human"] = False
            existing["decision"] = None
            existing["resolution_note"] = None
            clear_claim(existing)
            existing["reopen_count"] = existing.get("reopen_count", 0) + 1
            existing["history"].append(history_event("reopened", "Finding reappeared after being closed"))
        existing["history"].append(history_event("seen-again", "Finding reappeared"))
        return item_id, False

    title = finding.get("title") or "Local review finding"
    body = finding.get("body") or finding.get("issue") or ""
    status = "OPEN"
    session["items"][item_id] = {
        "item_id": item_id,
        "item_kind": "local_finding",
        "source": source,
        "origin_ref": fingerprint,
        "path": finding.get("path"),
        "line": finding.get("line"),
        "start_line": finding.get("start_line"),
        "end_line": finding.get("end_line"),
        "title": title,
        "body": body,
        "severity": finding.get("severity") or "P2",
        "confidence": finding.get("confidence"),
        "category": finding.get("category") or "general",
        "status": status,
        "decision": None,
        "blocking": blocking_for_status(status),
        "handled": False,
        "handled_at": None,
        "handled_run_id": None,
        "resolution_note": None,
        "published": False,
        "published_ref": None,
        "url": None,
        "is_outdated": False,
        "scan_id": session.get("current_scan_id"),
        "introduced_in_sha": finding.get("head_sha"),
        "last_seen_in_sha": finding.get("head_sha"),
        "claimed_by": None,
        "claimed_at": None,
        "lease_expires_at": None,
        "repeat_count": 0,
        "reopen_count": 0,
        "linked_github_item_id": None,
        "evidence": [],
        "auto_attempt_count": 0,
        "last_auto_action": None,
        "last_auto_failure": None,
        "needs_human": False,
        "history": [history_event("created", "Imported from local review")],
        "created_at": now,
        "created_run_id": run_id,
        "updated_at": now,
    }
    return item_id, True


def ensure_item(session: dict, item_id: str) -> dict:
    try:
        return session["items"][item_id]
    except KeyError as exc:
        raise SystemExit(f"Unknown item: {item_id}") from exc


def reconcile_published_findings(session: dict):
    run_id = current_run_id(session)
    github_items = [item for item in session["items"].values() if item["item_kind"] == "github_thread"]
    for item in session["items"].values():
        if item["item_kind"] != "local_finding" or item["status"] != "PUBLISHED":
            continue
        for github_item in github_items:
            github_urls = {value for value in (github_item.get("url"), github_item.get("first_url"), github_item.get("latest_url")) if value}
            same_url = bool(item.get("url")) and item.get("url") in github_urls
            same_location = item.get("path") == github_item.get("path") and item.get("line") == github_item.get("line")
            same_body = normalize_text(item.get("body", "")) == normalize_text(github_item.get("body", ""))
            if same_url or (same_location and same_body):
                now = utc_now()
                item["linked_github_item_id"] = github_item["item_id"]
                item["status"] = "CLOSED"
                item["blocking"] = False
                set_handled_state(
                    item,
                    True,
                    run_id=run_id,
                    now=now,
                    preserve_existing=bool(item.get("handled")),
                )
                item["updated_at"] = now
                clear_claim(item)
                item["history"].append(history_event("linked", f"Linked to {github_item['item_id']}"))
                break


def validate_transition(current_status: str, next_status: str):
    if current_status == next_status:
        return
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if next_status not in allowed:
        raise SystemExit(f"Illegal status transition: {current_status} -> {next_status}")


def require_note(status: str, note: str):
    if status in STATUSES_REQUIRING_NOTE and not note.strip():
        raise SystemExit(f"Status {status} requires --note")


def cmd_init(args):
    path = session_path(args.repo, args.pr_number)
    if path.exists():
        session = load_session(args.repo, args.pr_number)
    else:
        session = default_session(args.repo, args.pr_number)
        save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "init",
        "ok",
        "Initialized PR session",
        {"session_file": str(path)},
        run_id=current_run_id(session),
    )
    print(f"Initialized session: {path}")
    return 0


def cmd_sync_github(args):
    session = load_session(args.repo, args.pr_number)
    rows = read_records_from_stdin()
    session["current_scan_id"] = args.scan_id or utc_now()
    created = 0
    for row in rows:
        _, was_created = upsert_github_thread(session, row)
        created += 1 if was_created else 0
    reconcile_published_findings(session)
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "sync-github",
        "ok",
        "Synchronized GitHub review threads",
        {"upserted_count": len(rows), "created_count": created, "scan_id": session["current_scan_id"]},
        run_id=current_run_id(session),
    )
    print(f"Upserted {len(rows)} GitHub item(s); created {created}.")
    return 0


def cmd_ingest_local(args):
    session = load_session(args.repo, args.pr_number)
    findings = [normalize_finding(record) for record in read_records_from_stdin()]
    session["current_scan_id"] = args.scan_id or utc_now()
    run_id = current_run_id(session)
    incoming_ids = {local_finding_item_id(args.source, finding) for finding in findings}
    created = 0
    for finding in findings:
        _, was_created = add_local_finding(session, finding, args.source)
        created += 1 if was_created else 0
    synced = 0
    if args.sync:
        now = utc_now()
        for item in session["items"].values():
            if item["item_kind"] != "local_finding":
                continue
            if item.get("source") != args.source:
                continue
            if item["item_id"] in incoming_ids:
                continue
            if item["status"] == "CLOSED":
                continue
            validate_transition(item["status"], "CLOSED")
            item["status"] = "CLOSED"
            item["blocking"] = False
            item["decision"] = "sync"
            set_handled_state(
                item,
                True,
                run_id=run_id,
                now=now,
                preserve_existing=bool(item.get("handled")),
            )
            item["updated_at"] = now
            item["resolution_note"] = "Auto-resolved because the finding disappeared from synchronized input."
            clear_claim(item)
            item["history"].append(history_event("auto-resolved", "Auto-resolved from synchronized findings", actor="ingest-local"))
            synced += 1
    if args.handoff_sha256:
        session["handoff"]["last_consumed_sha256"] = args.handoff_sha256
    save_session(session)
    active_local_items = sum(1 for item in session["items"].values() if item["item_kind"] == "local_finding" and item.get("blocking"))
    append_audit_event(
        args.repo,
        args.pr_number,
        "ingest-local",
        "ok",
        "Imported local review findings",
        {
            "received_count": len(findings),
            "created_count": created,
            "synced_count": synced,
            "active_local_items_count": active_local_items,
            "source": args.source,
            "scan_id": session["current_scan_id"],
            "sync_enabled": bool(args.sync),
        },
        run_id=current_run_id(session),
    )
    print(f"Created {created} local item(s) from {len(findings)} finding(s). Existing active local item(s): {active_local_items}.")
    if args.sync:
        print(f"Synced {synced} missing local item(s) to CLOSED.")
    return 0


def cmd_claim(args):
    session = load_session(args.repo, args.pr_number)
    item = ensure_item(session, args.item_id)
    now = datetime.now(timezone.utc)
    validate_transition(item["status"], "CLAIMED")
    lease_expires_at = item.get("lease_expires_at")
    if item.get("claimed_by") and lease_expires_at:
        expires = datetime.fromisoformat(lease_expires_at)
        if expires > now and item["claimed_by"] != args.agent:
            raise SystemExit(f"Item already claimed by {item['claimed_by']} until {lease_expires_at}")

    item["claimed_by"] = args.agent
    item["claimed_at"] = utc_now()
    item["lease_expires_at"] = (now + timedelta(minutes=args.minutes)).replace(microsecond=0).isoformat()
    item["status"] = "CLAIMED"
    item["blocking"] = True
    item["history"].append(history_event("claimed", f"Claimed by {args.agent}", actor=args.agent))
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "claim",
        "ok",
        "Claimed item",
        {"item_id": args.item_id, "agent": args.agent},
        run_id=current_run_id(session),
    )
    print(f"Claimed item: {args.item_id} by {args.agent}")
    return 0


def cmd_update_item(args):
    if args.status not in VALID_STATUSES:
        raise SystemExit(f"Invalid status: {args.status}")
    session = load_session(args.repo, args.pr_number)
    run_id = current_run_id(session)
    item = ensure_item(session, args.item_id)
    previous_status = item["status"]
    validate_transition(item["status"], args.status)
    require_note(args.status, args.note)
    item["status"] = args.status
    item["blocking"] = blocking_for_status(args.status)
    item["updated_at"] = utc_now()
    if args.status == "OPEN" and previous_status in {"DEFERRED", "CLARIFIED", "CLOSED", "STALE", "DROPPED"}:
        item["reopen_count"] = item.get("reopen_count", 0) + 1
    if item.get("needs_human"):
        item["needs_human"] = False
    if args.status == "OPEN":
        clear_claim(item)
    if item["item_kind"] == "local_finding" and args.status in {"CLARIFIED", "DEFERRED", "VERIFIED", "CLOSED"}:
        set_handled_state(
            item,
            True,
            run_id=run_id,
            now=item["updated_at"],
            preserve_existing=bool(item.get("handled")),
        )
    elif args.status == "OPEN":
        set_handled_state(item, False, run_id=None)
    elif args.handled:
        set_handled_state(
            item,
            True,
            run_id=run_id,
            now=item["updated_at"],
            preserve_existing=bool(item.get("handled")),
        )
    else:
        set_handled_state(
            item,
            not item["blocking"],
            run_id=run_id if not item["blocking"] else None,
            now=item["updated_at"],
            preserve_existing=bool(item.get("handled")) and not item["blocking"],
        )
    if args.decision:
        item["decision"] = args.decision
    if args.note:
        item["resolution_note"] = args.note
        item["history"].append(history_event("status-updated", args.note, actor=args.actor))
    if args.status in NON_BLOCKING_STATUSES and args.status != "OPEN":
        clear_claim(item)
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "update-item",
        "ok",
        "Updated item status",
        {"item_id": args.item_id, "status": args.status, "actor": args.actor},
        run_id=current_run_id(session),
    )
    print(f"Updated item: {args.item_id} -> {args.status}")
    return 0



def cmd_update_items_batch(args):
    session = load_session(args.repo, args.pr_number)
    run_id = current_run_id(session)
    updates = read_records_from_stdin()
    for update in updates:
        item_id = update["item_id"]
        status = update.get("status")
        item = ensure_item(session, item_id)
        if status:
            validate_transition(item["status"], status)
            item["status"] = status
            item["blocking"] = blocking_for_status(status)
        item["updated_at"] = utc_now()
        if update.get("handled") is not None:
            set_handled_state(
                item,
                update["handled"],
                run_id=run_id if update["handled"] else None,
                now=item["updated_at"],
                preserve_existing=bool(item.get("handled")) and bool(update["handled"]),
            )
        elif status is not None and not item["blocking"]:
            set_handled_state(
                item,
                True,
                run_id=run_id,
                now=item["updated_at"],
                preserve_existing=bool(item.get("handled")),
            )
        elif status is not None and item["blocking"]:
            set_handled_state(item, False, run_id=None)
        if update.get("decision"):
            item["decision"] = update["decision"]
        note = update.get("note")
        if note:
            item["resolution_note"] = note
            item["history"].append(history_event("status-updated-batch", note, actor=update.get("actor", "system")))
        if update.get("reply_posted"):
            item["reply_posted"] = True
        if update.get("reply_url"):
            item["reply_url"] = update["reply_url"]
        if update.get("last_auto_action"):
            item["last_auto_action"] = update["last_auto_action"]
        if "last_auto_failure" in update:
            item["last_auto_failure"] = update["last_auto_failure"]
        if update.get("needs_human") is not None:
            item["needs_human"] = update["needs_human"]
        if update.get("clear_claim"):
            clear_claim(item)
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "update-items-batch",
        "ok",
        "Updated items in batch",
        {"count": len(updates)},
        run_id=current_run_id(session),
    )
    print(f"Updated {len(updates)} items.")
    return 0

def cmd_reclaim_stale_claims(args):
    session = load_session(args.repo, args.pr_number)
    now = datetime.now(timezone.utc)
    reclaimed = 0
    for item in session["items"].values():
        lease_expires_at = item.get("lease_expires_at")
        if not item.get("claimed_by") or not lease_expires_at:
            continue
        expires = datetime.fromisoformat(lease_expires_at)
        if expires <= now:
            reclaimed += 1
            item["claimed_by"] = None
            item["claimed_at"] = None
            item["lease_expires_at"] = None
            if item["status"] == "CLAIMED":
                item["status"] = "OPEN"
                item["blocking"] = True
            item["history"].append(history_event("claim-reclaimed", "Reclaimed expired lease"))
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "reclaim-stale-claims",
        "ok",
        "Reclaimed expired claims",
        {"reclaimed_count": reclaimed},
        run_id=current_run_id(session),
    )
    print(f"Reclaimed {reclaimed} stale claim(s).")
    return 0


def cmd_close_item(args):
    session = load_session(args.repo, args.pr_number)
    run_id = current_run_id(session)
    item = ensure_item(session, args.item_id)
    validate_transition(item["status"], "CLOSED")
    require_note("CLOSED", args.note)
    item["status"] = "CLOSED"
    item["blocking"] = False
    handled_at = utc_now()
    set_handled_state(item, True, run_id=run_id, now=handled_at, preserve_existing=bool(item.get("handled")))
    clear_claim(item)
    item["updated_at"] = handled_at
    item["resolution_note"] = args.note
    item["history"].append(history_event("closed", args.note or "Closed item", actor=args.actor))
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "close-item",
        "ok",
        "Closed item",
        {"item_id": args.item_id, "actor": args.actor},
        run_id=current_run_id(session),
    )
    print(f"Closed item: {args.item_id}")
    return 0


def cmd_resolve_local_item(args):
    session = load_session(args.repo, args.pr_number)
    run_id = current_run_id(session)
    item = ensure_item(session, args.item_id)
    if item["item_kind"] != "local_finding":
        raise SystemExit("resolve-local-item only supports local_finding items.")
    target_status = {"fix": "CLOSED", "clarify": "CLARIFIED", "defer": "DEFERRED"}[args.resolution]
    require_note(target_status, args.note)

    if args.resolution == "fix":
        validate_transition(item["status"], "CLOSED")
        item["status"] = "CLOSED"
        item["decision"] = "accept"
        item["history"].append(history_event("accepted", args.note, actor=args.actor))
        item["history"].append(history_event("fixed", args.note, actor=args.actor))
        item["history"].append(history_event("verified", args.note, actor=args.actor))
        item["history"].append(history_event("closed", args.note, actor=args.actor))
    elif args.resolution == "clarify":
        validate_transition(item["status"], "CLARIFIED")
        item["status"] = "CLARIFIED"
        item["decision"] = "clarify"
        item["history"].append(history_event("clarified", args.note, actor=args.actor))
    else:
        validate_transition(item["status"], "DEFERRED")
        item["status"] = "DEFERRED"
        item["decision"] = "defer"
        item["history"].append(history_event("deferred", args.note, actor=args.actor))

    item["blocking"] = blocking_for_status(item["status"])
    item["updated_at"] = utc_now()
    set_handled_state(
        item,
        not item["blocking"],
        run_id=run_id if not item["blocking"] else None,
        now=item["updated_at"],
        preserve_existing=bool(item.get("handled")) and not item["blocking"],
    )
    clear_claim(item)
    item["resolution_note"] = args.note
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "resolve-local-item",
        "ok",
        "Applied terminal resolution to local finding",
        {"item_id": args.item_id, "resolution": args.resolution, "actor": args.actor},
        run_id=current_run_id(session),
    )
    print(f"Resolved local item: {args.item_id} -> {item['status']}")
    return 0


def cmd_mark_published(args):
    session = load_session(args.repo, args.pr_number)
    item = ensure_item(session, args.item_id)
    if item["item_kind"] != "local_finding":
        raise SystemExit("Only local_finding items can be marked published.")
    validate_transition(item["status"], "PUBLISHED")
    require_note("PUBLISHED", args.note)
    item["status"] = "PUBLISHED"
    item["blocking"] = True
    set_handled_state(item, False, run_id=None)
    item["published"] = True
    item["published_ref"] = args.published_ref
    item["url"] = args.url
    item["updated_at"] = utc_now()
    item["resolution_note"] = args.note
    item["history"].append(history_event("published", args.note, actor=args.actor))
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "mark-published",
        "ok",
        "Marked local finding as published",
        {"item_id": args.item_id, "published_ref": args.published_ref, "url": args.url, "actor": args.actor},
        run_id=current_run_id(session),
    )
    print(f"Marked published: {args.item_id}")
    return 0


def cmd_mark_handled(args):
    session = load_session(args.repo, args.pr_number)
    run_id = current_run_id(session)
    item = ensure_item(session, args.item_id)
    handled_at = utc_now()
    set_handled_state(item, True, run_id=run_id, now=handled_at, preserve_existing=bool(item.get("handled")))
    item["updated_at"] = handled_at
    item["resolution_note"] = args.note or item.get("resolution_note")
    item["history"].append(history_event("handled", args.note or "Marked handled", actor=args.actor))
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "mark-handled",
        "ok",
        "Marked item handled",
        {"item_id": args.item_id, "actor": args.actor},
        run_id=current_run_id(session),
    )
    print(f"Marked handled: {args.item_id}")
    return 0


def cmd_list_items(args):
    session = load_session(args.repo, args.pr_number)
    items = list(session["items"].values())
    if args.item_kind:
        items = [item for item in items if item["item_kind"] == args.item_kind]
    if args.status:
        items = [item for item in items if item["status"] in set(args.status)]
    if args.unhandled:
        items = [item for item in items if not item.get("handled")]
    for item in sorted(items, key=lambda row: (row.get("severity", "P9"), row.get("path") or "", row.get("line") or 0)):
        print(json.dumps(item, sort_keys=True))
    return 0


def cmd_gate(args):
    session = load_session(args.repo, args.pr_number)
    blocking = [item for item in session["items"].values() if item.get("blocking")]
    invalid_local_items = [
        item
        for item in session["items"].values()
        if item["item_kind"] == "local_finding"
        and item["status"] in {"CLARIFIED", "DEFERRED", "FIXED", "VERIFIED", "CLOSED", "PUBLISHED"}
        and not (item.get("resolution_note") or "").strip()
    ]
    invalid_github_reply_items = [
        item
        for item in session["items"].values()
        if item["item_kind"] == "github_thread"
        and item["status"] in GITHUB_TERMINAL_STATUSES
        and not item_has_reply_evidence(item)
    ]
    loop_warning_items = [
        item
        for item in session["items"].values()
        if item["item_kind"] == "local_finding"
        and max(item.get("repeat_count", 0), item.get("reopen_count", 0)) >= LOOP_WARNING_THRESHOLD
        and item.get("blocking")
    ]
    unresolved_threads = [
        item
        for item in session["items"].values()
        if item["item_kind"] == "github_thread" and item["status"] not in GITHUB_TERMINAL_STATUSES
    ]
    session_gate = "PASS" if not blocking and not invalid_local_items and not invalid_github_reply_items and not loop_warning_items else "FAIL"
    remote_gate = "PASS" if not unresolved_threads else "FAIL"
    progress = gate_progress_counts(session, blocking, unresolved_threads)
    summary = summary_path(args.repo, args.pr_number)
    lines = [
        "# Audit Summary",
        "",
        f"- repo: {args.repo}",
        f"- pr: {args.pr_number}",
        f"- session_gate: {session_gate}",
        f"- remote_gate: {remote_gate}",
        f"- blocking_items_count: {len(blocking)}",
        f"- unresolved_github_threads_count: {len(unresolved_threads)}",
        f"- invalid_local_items_count: {len(invalid_local_items)}",
        f"- github_threads_missing_reply_count: {len(invalid_github_reply_items)}",
        f"- loop_warning_items_count: {len(loop_warning_items)}",
    ]
    if blocking:
        lines.extend(["", "## Blocking Items"])
        lines.extend(
            f"- {item['item_id']} status={item['status']} path={item.get('path') or '-'} line={item.get('line') or '-'}"
            for item in blocking
        )
    if invalid_local_items:
        lines.extend(["", "## Invalid Local Items"])
        lines.extend(
            f"- {item['item_id']} status={item['status']} missing=resolution_note"
            for item in invalid_local_items
        )
    if invalid_github_reply_items:
        lines.extend(["", "## Invalid GitHub Reply Items"])
        lines.extend(
            f"- {item['item_id']} status={item['status']} path={item.get('path') or '-'} line={item.get('line') or '-'} missing=reply_evidence"
            for item in invalid_github_reply_items
        )
    if loop_warning_items:
        lines.extend(["", "## Loop Warning Items"])
        lines.extend(
            f"- {item['item_id']} repeat_count={item.get('repeat_count',0)} reopen_count={item.get('reopen_count',0)}"
            for item in loop_warning_items
        )
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    digest = sha256_of_file(summary)
    append_audit_event(
        args.repo,
        args.pr_number,
        "gate",
        "ok" if session_gate == "PASS" and remote_gate == "PASS" else "failed",
        "Evaluated session gate",
        {
            "session_gate": session_gate,
            "remote_gate": remote_gate,
            "blocking_items_count": len(blocking),
            "invalid_local_items_count": len(invalid_local_items),
            "github_threads_missing_reply_count": len(invalid_github_reply_items),
            "loop_warning_items_count": len(loop_warning_items),
            **progress,
            "summary_file": str(summary),
            "summary_sha256": digest,
        },
        run_id=current_run_id(session),
    )
    print(f"SESSION GATE {session_gate}")
    print(f"REMOTE GATE {remote_gate}")
    print(f"blocking_items_count={len(blocking)}")
    print(f"unresolved_github_threads_count={len(unresolved_threads)}")
    print(f"invalid_local_items_count={len(invalid_local_items)}")
    print(f"github_threads_missing_reply_count={len(invalid_github_reply_items)}")
    print(f"loop_warning_items_count={len(loop_warning_items)}")
    print(f"tracked_items_count={progress['tracked_items_count']}")
    print(f"handled_items_count={progress['handled_items_count']}")
    print(f"github_threads_total_count={progress['github_threads_total_count']}")
    print(f"github_threads_handled_count={progress['github_threads_handled_count']}")
    print(f"github_threads_new_count={progress['github_threads_new_count']}")
    print(f"github_threads_handled_this_run_count={progress['github_threads_handled_this_run_count']}")
    print(f"github_threads_unresolved_count={progress['github_threads_unresolved_count']}")
    print(f"local_findings_total_count={progress['local_findings_total_count']}")
    print(f"local_findings_handled_count={progress['local_findings_handled_count']}")
    print(f"local_findings_new_count={progress['local_findings_new_count']}")
    print(f"local_findings_handled_this_run_count={progress['local_findings_handled_this_run_count']}")
    print(f"local_findings_unresolved_count={progress['local_findings_unresolved_count']}")
    print(f"local_findings_blocking_count={progress['local_findings_blocking_count']}")
    print(f"audit_summary={summary}")
    print(f"audit_summary_sha256={digest}")
    return 0 if session_gate == "PASS" and remote_gate == "PASS" else 1


def build_parser():
    parser = argparse.ArgumentParser(description="PR session engine for gh-address-cr")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("repo")
    init.add_argument("pr_number")
    init.set_defaults(func=cmd_init)

    sync_github = sub.add_parser("sync-github")
    sync_github.add_argument("repo")
    sync_github.add_argument("pr_number")
    sync_github.add_argument("--scan-id")
    sync_github.set_defaults(func=cmd_sync_github)

    ingest_local = sub.add_parser("ingest-local")
    ingest_local.add_argument("repo")
    ingest_local.add_argument("pr_number")
    ingest_local.add_argument("--source", required=True)
    ingest_local.add_argument("--scan-id")
    ingest_local.add_argument("--sync", action="store_true")
    ingest_local.add_argument("--handoff-sha256", default="")
    ingest_local.set_defaults(func=cmd_ingest_local)

    claim = sub.add_parser("claim")
    claim.add_argument("repo")
    claim.add_argument("pr_number")
    claim.add_argument("item_id")
    claim.add_argument("--agent", required=True)
    claim.add_argument("--minutes", type=int, default=DEFAULT_CLAIM_MINUTES)
    claim.set_defaults(func=cmd_claim)

    update_item = sub.add_parser("update-item")
    update_item.add_argument("repo")
    update_item.add_argument("pr_number")
    update_item.add_argument("item_id")
    update_item.add_argument("status")
    update_item.add_argument("--decision")
    update_item.add_argument("--note", default="")
    update_item.add_argument("--actor", default="system")
    update_item.add_argument("--handled", action="store_true")
    update_item.set_defaults(func=cmd_update_item)


    update_items_batch = sub.add_parser("update-items-batch")
    update_items_batch.add_argument("repo")
    update_items_batch.add_argument("pr_number")
    update_items_batch.set_defaults(func=cmd_update_items_batch)

    mark_handled = sub.add_parser("mark-handled")
    mark_handled.add_argument("repo")
    mark_handled.add_argument("pr_number")
    mark_handled.add_argument("item_id")
    mark_handled.add_argument("--note", default="")
    mark_handled.add_argument("--actor", default="system")
    mark_handled.set_defaults(func=cmd_mark_handled)

    list_items = sub.add_parser("list-items")
    list_items.add_argument("repo")
    list_items.add_argument("pr_number")
    list_items.add_argument("--item-kind")
    list_items.add_argument("--status", action="append")
    list_items.add_argument("--unhandled", action="store_true")
    list_items.set_defaults(func=cmd_list_items)

    gate = sub.add_parser("gate")
    gate.add_argument("repo")
    gate.add_argument("pr_number")
    gate.set_defaults(func=cmd_gate)

    close_item = sub.add_parser("close-item")
    close_item.add_argument("repo")
    close_item.add_argument("pr_number")
    close_item.add_argument("item_id")
    close_item.add_argument("--note", default="")
    close_item.add_argument("--actor", default="system")
    close_item.set_defaults(func=cmd_close_item)

    resolve_local_item = sub.add_parser("resolve-local-item")
    resolve_local_item.add_argument("repo")
    resolve_local_item.add_argument("pr_number")
    resolve_local_item.add_argument("item_id")
    resolve_local_item.add_argument("resolution", choices=["fix", "clarify", "defer"])
    resolve_local_item.add_argument("--note", required=True)
    resolve_local_item.add_argument("--actor", default="system")
    resolve_local_item.set_defaults(func=cmd_resolve_local_item)

    mark_published = sub.add_parser("mark-published")
    mark_published.add_argument("repo")
    mark_published.add_argument("pr_number")
    mark_published.add_argument("item_id")
    mark_published.add_argument("--published-ref", required=True)
    mark_published.add_argument("--url", default="")
    mark_published.add_argument("--note", default="")
    mark_published.add_argument("--actor", default="system")
    mark_published.set_defaults(func=cmd_mark_published)

    reclaim_claims = sub.add_parser("reclaim-stale-claims")
    reclaim_claims.add_argument("repo")
    reclaim_claims.add_argument("pr_number")
    reclaim_claims.set_defaults(func=cmd_reclaim_stale_claims)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON input: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc, file=sys.stderr)
            return int(exc.code) if isinstance(exc.code, int) else 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
