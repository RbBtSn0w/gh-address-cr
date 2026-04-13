#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA_VERSION = 1
DEFAULT_CLAIM_MINUTES = 30
LOOP_WARNING_THRESHOLD = 3
BLOCKING_STATUSES = {"OPEN", "CLAIMED", "ACCEPTED", "FIX_IN_PROGRESS", "FIXED", "PUBLISHED"}
NON_BLOCKING_STATUSES = {"VERIFIED", "CLARIFIED", "DEFERRED", "CLOSED", "DROPPED", "STALE"}
VALID_STATUSES = BLOCKING_STATUSES | NON_BLOCKING_STATUSES
GITHUB_TERMINAL_STATUSES = {"CLOSED", "DROPPED", "STALE"}
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


def repo_key(repo: str) -> str:
    return repo.replace("/", "__")


def state_dir() -> Path:
    override = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
    if override:
        return Path(override)

    home = os.environ.get("HOME")
    if sys.platform == "darwin":
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/Library/Caches" if home else None)
    else:
        base = os.environ.get("XDG_CACHE_HOME") or (f"{home}/.cache" if home else None)
    if not base:
        raise SystemExit("Unable to determine state directory. Set GH_ADDRESS_CR_STATE_DIR.")
    return Path(base) / "gh-address-cr"


def ensure_state_dir() -> Path:
    path = state_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_path(repo: str, pr_number: str) -> Path:
    return ensure_state_dir() / f"{repo_key(repo)}__pr{pr_number}__session.json"


def audit_log_path(repo: str, pr_number: str) -> Path:
    return ensure_state_dir() / f"{repo_key(repo)}__pr{pr_number}__audit.jsonl"


def summary_path(repo: str, pr_number: str) -> Path:
    return ensure_state_dir() / f"{repo_key(repo)}__pr{pr_number}__audit_summary.md"


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


def append_audit_event(repo: str, pr_number: str, action: str, status: str, message: str, details=None):
    event = {
        "timestamp": utc_now(),
        "action": action,
        "status": status,
        "repo": repo,
        "pr": pr_number,
        "message": message,
        "details": details or {},
    }
    with audit_log_path(repo, pr_number).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


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
        },
        "items": {},
        "history": [],
    }


def load_session(repo: str, pr_number: str) -> dict:
    path = session_path(repo, pr_number)
    if not path.exists():
        raise SystemExit(f"Session not found: {path}. Run `init` first.")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"Unsupported session schema version: {payload.get('schema_version')}")
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
    }


def blocking_for_status(status: str) -> bool:
    return status in BLOCKING_STATUSES


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
    resolved = bool(row.get("isResolved"))
    status = "CLOSED" if resolved else "OPEN"
    existing = session["items"].get(item_id)
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
        "handled": (existing.get("handled") if existing else False) or resolved,
        "handled_at": existing.get("handled_at") if existing and existing.get("handled_at") else (now if resolved else None),
        "resolution_note": existing.get("resolution_note") if existing else None,
        "published": True,
        "published_ref": row.get("url"),
        "url": row.get("url"),
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
        "created_at": existing.get("created_at") if existing else now,
        "updated_at": now,
    }
    created = existing is None
    if created:
        payload["history"].append(history_event("created", "Imported from GitHub"))
    else:
        payload["history"].append(history_event("synced", "Refreshed from GitHub"))
    session["items"][item_id] = payload
    return item_id, created


def add_local_finding(session: dict, finding: dict, source: str) -> tuple[str, bool]:
    fingerprint = fingerprint_finding(finding)
    item_id = f"local-finding:{fingerprint}"
    now = utc_now()
    existing = session["items"].get(item_id)
    if existing:
        existing["last_seen_in_sha"] = finding.get("head_sha") or existing.get("last_seen_in_sha")
        existing["scan_id"] = session.get("current_scan_id")
        existing["updated_at"] = now
        existing["repeat_count"] = existing.get("repeat_count", 0) + 1
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
        "history": [history_event("created", "Imported from local review")],
        "created_at": now,
        "updated_at": now,
    }
    return item_id, True


def ensure_item(session: dict, item_id: str) -> dict:
    try:
        return session["items"][item_id]
    except KeyError as exc:
        raise SystemExit(f"Unknown item: {item_id}") from exc


def reconcile_published_findings(session: dict):
    github_items = [item for item in session["items"].values() if item["item_kind"] == "github_thread"]
    for item in session["items"].values():
        if item["item_kind"] != "local_finding" or item["status"] != "PUBLISHED":
            continue
        for github_item in github_items:
            same_url = item.get("url") and item.get("url") == github_item.get("url")
            same_location = item.get("path") == github_item.get("path") and item.get("line") == github_item.get("line")
            same_body = normalize_text(item.get("body", "")) == normalize_text(github_item.get("body", ""))
            if same_url or (same_location and same_body):
                item["linked_github_item_id"] = github_item["item_id"]
                item["status"] = "CLOSED"
                item["blocking"] = False
                item["handled"] = True
                item["handled_at"] = utc_now()
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
    append_audit_event(args.repo, args.pr_number, "init", "ok", "Initialized PR session", {"session_file": str(path)})
    print(f"Initialized session: {path}")
    return 0


def cmd_sync_github(args):
    session = load_session(args.repo, args.pr_number)
    rows = read_records_from_stdin()
    session["current_scan_id"] = args.scan_id or utc_now()
    created = 0
    touched = []
    for row in rows:
        item_id, was_created = upsert_github_thread(session, row)
        created += 1 if was_created else 0
        touched.append(item_id)
    reconcile_published_findings(session)
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "sync-github",
        "ok",
        "Synchronized GitHub review threads",
        {"upserted_count": len(rows), "created_count": created, "scan_id": session["current_scan_id"]},
    )
    print(f"Upserted {len(rows)} GitHub item(s); created {created}.")
    return 0


def cmd_ingest_local(args):
    session = load_session(args.repo, args.pr_number)
    findings = read_records_from_stdin()
    session["current_scan_id"] = args.scan_id or utc_now()
    created = 0
    for finding in findings:
        _, was_created = add_local_finding(session, finding, args.source)
        created += 1 if was_created else 0
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "ingest-local",
        "ok",
        "Imported local review findings",
        {"received_count": len(findings), "created_count": created, "source": args.source, "scan_id": session["current_scan_id"]},
    )
    print(f"Created {created} local item(s) from {len(findings)} finding(s).")
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
    append_audit_event(args.repo, args.pr_number, "claim", "ok", "Claimed item", {"item_id": args.item_id, "agent": args.agent})
    print(f"Claimed item: {args.item_id} by {args.agent}")
    return 0


def cmd_update_item(args):
    if args.status not in VALID_STATUSES:
        raise SystemExit(f"Invalid status: {args.status}")
    session = load_session(args.repo, args.pr_number)
    item = ensure_item(session, args.item_id)
    previous_status = item["status"]
    validate_transition(item["status"], args.status)
    require_note(args.status, args.note)
    item["status"] = args.status
    item["blocking"] = blocking_for_status(args.status)
    item["updated_at"] = utc_now()
    if args.status == "OPEN" and previous_status in {"DEFERRED", "CLARIFIED", "CLOSED", "STALE", "DROPPED"}:
        item["reopen_count"] = item.get("reopen_count", 0) + 1
    if item["item_kind"] == "local_finding" and args.status in {"CLARIFIED", "DEFERRED", "VERIFIED", "CLOSED"}:
        item["handled"] = True
        item["handled_at"] = utc_now()
    if args.handled:
        item["handled"] = True
        item["handled_at"] = utc_now()
    if args.decision:
        item["decision"] = args.decision
    if args.note:
        item["resolution_note"] = args.note
        item["history"].append(history_event("status-updated", args.note, actor=args.actor))
    if args.status in NON_BLOCKING_STATUSES:
        clear_claim(item)
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "update-item",
        "ok",
        "Updated item status",
        {"item_id": args.item_id, "status": args.status, "actor": args.actor},
    )
    print(f"Updated item: {args.item_id} -> {args.status}")
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
    )
    print(f"Reclaimed {reclaimed} stale claim(s).")
    return 0


def cmd_close_item(args):
    session = load_session(args.repo, args.pr_number)
    item = ensure_item(session, args.item_id)
    validate_transition(item["status"], "CLOSED")
    require_note("CLOSED", args.note)
    item["status"] = "CLOSED"
    item["blocking"] = False
    item["handled"] = True
    item["handled_at"] = utc_now()
    clear_claim(item)
    item["updated_at"] = utc_now()
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
    )
    print(f"Closed item: {args.item_id}")
    return 0


def cmd_resolve_local_item(args):
    session = load_session(args.repo, args.pr_number)
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
    item["handled"] = not item["blocking"]
    item["handled_at"] = utc_now() if item["handled"] else None
    clear_claim(item)
    item["updated_at"] = utc_now()
    item["resolution_note"] = args.note
    save_session(session)
    append_audit_event(
        args.repo,
        args.pr_number,
        "resolve-local-item",
        "ok",
        "Applied terminal resolution to local finding",
        {"item_id": args.item_id, "resolution": args.resolution, "actor": args.actor},
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
    )
    print(f"Marked published: {args.item_id}")
    return 0


def cmd_mark_handled(args):
    session = load_session(args.repo, args.pr_number)
    item = ensure_item(session, args.item_id)
    item["handled"] = True
    item["handled_at"] = utc_now()
    item["updated_at"] = utc_now()
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
    )
    print(f"Marked handled: {args.item_id}")
    return 0


def cmd_list_items(args):
    session = load_session(args.repo, args.pr_number)
    items = list(session["items"].values())
    if args.item_kind:
        items = [item for item in items if item["item_kind"] == args.item_kind]
    if args.status:
        items = [item for item in items if item["status"] == args.status]
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
    session_gate = "PASS" if not blocking and not invalid_local_items and not loop_warning_items else "FAIL"
    remote_gate = "PASS" if not unresolved_threads else "FAIL"
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
            "loop_warning_items_count": len(loop_warning_items),
            "summary_file": str(summary),
            "summary_sha256": digest,
        },
    )
    print(f"SESSION GATE {session_gate}")
    print(f"REMOTE GATE {remote_gate}")
    print(f"blocking_items_count={len(blocking)}")
    print(f"unresolved_github_threads_count={len(unresolved_threads)}")
    print(f"invalid_local_items_count={len(invalid_local_items)}")
    print(f"loop_warning_items_count={len(loop_warning_items)}")
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
    list_items.add_argument("--status")
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
