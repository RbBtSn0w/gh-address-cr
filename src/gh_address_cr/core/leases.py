from __future__ import annotations

import posixpath
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from gh_address_cr.core import session as session_store
from gh_address_cr.core.utils import (
    coerce_now as _coerce_now,
    get_field as _get,
    get_session_ledger as _ledger,
    json_ready as _json_ready,
    return_expired_items_to_open as _return_expired_items_to_open,
    set_field as _set,
)

try:
    from gh_address_cr.core.models import ClaimLease as _ModelClaimLease
    from gh_address_cr.core.models import LeaseRecoveryState
except ImportError:
    _ModelClaimLease = None
    LeaseRecoveryState = None


ACTIVE_LEASE_STATUSES = {"active", "submitted"}
TERMINAL_LEASE_STATUSES = {"accepted", "rejected", "expired", "released"}
READ_ONLY_ROLES = {"triage", "verifier", "review_producer", "gatekeeper"}


@dataclass
class _FallbackClaimLease:
    lease_id: str
    item_id: str
    agent_id: str
    role: str
    status: str
    created_at: datetime
    expires_at: datetime
    resume_token: str | None
    request_hash: str
    request_id: str | None = None
    request_path: str | None = None
    conflict_keys: tuple[str, ...] = ()
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    reason: str | None = None


ClaimLease = _ModelClaimLease or _FallbackClaimLease


class LeaseError(ValueError):
    def __init__(
        self,
        reason_code: str,
        detail: str | None = None,
        *,
        recovery_state: dict[str, Any] | None = None,
    ):
        self.reason_code = reason_code
        self.recovery_state = recovery_state
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


class LeaseConflictError(LeaseError):
    pass


class LeaseSubmissionError(LeaseError):
    pass


def claim_lease(
    session: Any,
    item: Any,
    *,
    agent_id: str,
    role: str,
    request_hash: str,
    lease_id: str | None = None,
    now: datetime | None = None,
    ttl_seconds: int = 3600,
    resume_token: str | None = None,
    request_id: str | None = None,
    request_path: str | None = None,
    conflict_keys: tuple[str, ...] | list[str] | None = None,
    allow_same_agent_github_thread_file_overlap: bool = False,
) -> Any:
    now = _coerce_now(now)
    expire_leases(session, now=now)

    item_id = _required(_get(item, "item_id"), "item_id")
    keys = tuple(sorted(set(conflict_keys if conflict_keys is not None else calculate_conflict_keys(item))))
    leases = _leases(session)

    for existing in leases.values():
        if _get(existing, "status") not in ACTIVE_LEASE_STATUSES:
            continue
        if _get(existing, "item_id") == item_id:
            raise LeaseConflictError("ITEM_ALREADY_LEASED", item_id)
        existing_keys = _conflict_keys(existing)
        overlap = set(keys).intersection(existing_keys)
        hunk_overlap = _hunk_overlap(keys, existing_keys)
        if hunk_overlap:
            overlap.update(hunk_overlap)
        if (
            overlap
            and not (is_read_only_role(role) and is_read_only_role(_get(existing, "role")))
            and not _same_agent_github_thread_file_overlap_allowed(
                existing,
                agent_id=agent_id,
                role=role,
                overlap=overlap,
                allow=allow_same_agent_github_thread_file_overlap,
            )
        ):
            raise LeaseConflictError("CONFLICT_KEYS_OVERLAP", ", ".join(sorted(overlap)))

    lease = _make_lease(
        lease_id=lease_id or f"lease_{uuid4().hex}",
        item_id=item_id,
        agent_id=agent_id,
        role=role,
        status="active",
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        resume_token=resume_token,
        request_hash=request_hash,
        request_id=request_id,
        request_path=request_path,
        conflict_keys=keys,
    )
    leases[_get(lease, "lease_id")] = lease
    _append_lease_event(session, lease, "lease_created", now=now)
    return lease


def submit_lease(
    session: Any,
    lease_id: str,
    *,
    agent_id: str,
    role: str,
    item_id: str,
    request_hash: str,
    now: datetime | None = None,
) -> Any:
    now = _coerce_now(now)
    lease = _find_lease(session, lease_id)

    status = _get(lease, "status")
    if status == "submitted":
        _raise_submission_error(
            session,
            "DUPLICATE_SUBMISSION",
            lease_id,
            lease=lease,
            agent_id=agent_id,
            role=role,
            item_id=item_id,
            request_hash=request_hash,
            now=now,
        )
    if status in TERMINAL_LEASE_STATUSES:
        _raise_submission_error(
            session,
            "STALE_LEASE",
            lease_id,
            lease=lease,
            agent_id=agent_id,
            role=role,
            item_id=item_id,
            request_hash=request_hash,
            now=now,
        )
    if status != "active":
        _raise_submission_error(
            session,
            "STALE_LEASE",
            lease_id,
            lease=lease,
            agent_id=agent_id,
            role=role,
            item_id=item_id,
            request_hash=request_hash,
            now=now,
        )
    if _get(lease, "role") != role:
        _raise_submission_error(
            session,
            "CROSS_ROLE_SUBMISSION",
            role,
            lease=lease,
            agent_id=agent_id,
            role=role,
            item_id=item_id,
            request_hash=request_hash,
            now=now,
        )
    if _get(lease, "agent_id") != agent_id:
        _raise_submission_error(
            session,
            "WRONG_AGENT",
            agent_id,
            lease=lease,
            agent_id=agent_id,
            role=role,
            item_id=item_id,
            request_hash=request_hash,
            now=now,
        )
    if _get(lease, "item_id") != item_id:
        _raise_submission_error(
            session,
            "WRONG_ITEM",
            item_id,
            lease=lease,
            agent_id=agent_id,
            role=role,
            item_id=item_id,
            request_hash=request_hash,
            now=now,
        )
    if _is_expired(lease, now):
        recovery = calculate_lease_recovery_state(
            session,
            lease_id,
            agent_id=agent_id,
            role=role,
            item_id=item_id,
            request_hash=request_hash,
            now=now,
        ).to_dict()
        _append_lease_recovery_event(session, recovery, now=now)
        _expire_lease(session, lease, now)
        raise LeaseSubmissionError("EXPIRED_LEASE", lease_id, recovery_state=recovery)
    if _get(lease, "request_hash") != request_hash:
        _raise_submission_error(
            session,
            "STALE_REQUEST_CONTEXT",
            lease_id,
            lease=lease,
            agent_id=agent_id,
            role=role,
            item_id=item_id,
            request_hash=request_hash,
            now=now,
        )

    _set(lease, "status", "submitted")
    _set(lease, "submitted_at", now)
    _append_lease_event(session, lease, "lease_submitted", now=now)
    return lease


def accept_lease(session: Any, lease_id: str, *, now: datetime | None = None) -> Any:
    now = _coerce_now(now)
    lease = _find_lease(session, lease_id)
    if _get(lease, "status") != "submitted":
        raise LeaseSubmissionError("STALE_LEASE", lease_id)
    _set(lease, "status", "accepted")
    _set(lease, "completed_at", now)
    _append_lease_event(session, lease, "lease_accepted", now=now)
    return lease


def reject_lease(
    session: Any,
    lease_id: str,
    *,
    now: datetime | None = None,
    reason: str | None = None,
) -> Any:
    now = _coerce_now(now)
    lease = _find_lease(session, lease_id)
    if _get(lease, "status") not in ACTIVE_LEASE_STATUSES:
        raise LeaseSubmissionError("STALE_LEASE", lease_id)
    _set(lease, "status", "rejected")
    _set(lease, "completed_at", now)
    _set(lease, "reason", reason)
    _append_lease_event(session, lease, "lease_rejected", now=now, reason=reason)
    return lease


def release_lease(
    session: Any,
    lease_id: str,
    *,
    now: datetime | None = None,
    reason: str | None = None,
) -> Any:
    now = _coerce_now(now)
    lease = _find_lease(session, lease_id)
    if _get(lease, "status") not in ACTIVE_LEASE_STATUSES:
        raise LeaseSubmissionError("STALE_LEASE", lease_id)
    _set(lease, "status", "released")
    _set(lease, "completed_at", now)
    _set(lease, "reason", reason)
    _append_lease_event(session, lease, "lease_released", now=now, reason=reason)
    return lease


def expire_leases(session: Any, *, now: datetime | None = None) -> list[Any]:
    now = _coerce_now(now)
    expired = []
    for lease in list(_leases(session).values()):
        if _get(lease, "status") in ACTIVE_LEASE_STATUSES and _is_expired(lease, now):
            _expire_lease(session, lease, now)
            expired.append(lease)
    return expired


def list_leases(repo: str, pr_number: str) -> dict[str, Any]:
    session = session_store.load_session(repo, pr_number)
    return {
        "status": "LEASES_READY",
        "repo": repo,
        "pr_number": str(pr_number),
        "leases": [_lease_listing_row(session, lease) for lease in session.get("leases", {}).values()],
    }


def reclaim_leases(repo: str, pr_number: str, *, now: datetime | None = None) -> dict[str, Any]:
    current_time = _coerce_now(now)
    session = session_store.load_session(repo, pr_number)
    ledger = _ledger(session)
    expired = expire_leases(session, now=current_time)
    _return_expired_items_to_open(session, expired)
    for lease in expired:
        ledger.append_event(
            session_id=str(session["session_id"]),
            item_id=str(_get(lease, "item_id")),
            lease_id=str(_get(lease, "lease_id")),
            agent_id=str(_get(lease, "agent_id")),
            role=str(_get(lease, "role")),
            event_type="lease_expired",
            payload={"reason": "reclaimed"},
        )
    session_store.save_session(repo, pr_number, session)
    return {
        "status": "LEASES_RECLAIMED",
        "repo": repo,
        "pr_number": str(pr_number),
        "expired_count": len(expired),
        "leases": [_json_ready(lease) for lease in expired],
    }


def _lease_listing_row(session: Any, lease: Any) -> dict[str, Any]:
    row = _json_ready(lease)
    row["lease_recovery"] = calculate_lease_recovery_state(
        session,
        str(_get(lease, "lease_id") or ""),
        agent_id=str(_get(lease, "agent_id") or ""),
        role=str(_get(lease, "role") or ""),
        item_id=str(_get(lease, "item_id") or ""),
        request_hash=str(_get(lease, "request_hash") or ""),
    ).to_dict()
    return row


def reclaim_lease(
    session: Any,
    item: Any,
    *,
    agent_id: str,
    role: str,
    request_hash: str,
    lease_id: str | None = None,
    now: datetime | None = None,
    ttl_seconds: int = 3600,
    resume_token: str | None = None,
    request_id: str | None = None,
    request_path: str | None = None,
) -> Any:
    now = _coerce_now(now)
    expire_leases(session, now=now)
    return claim_lease(
        session,
        item,
        agent_id=agent_id,
        role=role,
        request_hash=request_hash,
        lease_id=lease_id,
        now=now,
        ttl_seconds=ttl_seconds,
        resume_token=resume_token,
        request_id=request_id,
        request_path=request_path,
    )


def calculate_lease_recovery_state(
    session: Any,
    lease_id: str,
    *,
    agent_id: str,
    role: str,
    item_id: str,
    request_hash: str,
    now: datetime | None = None,
) -> Any:
    now = _coerce_now(now)
    lease = _leases(session).get(lease_id)
    lease_item_id = _recovery_field(_get(lease, "item_id") if lease is not None else None, default=item_id)
    item = _items(session).get(lease_item_id) if lease is not None else _items(session).get(item_id)
    lease_status = _recovery_field(_get(lease, "status") if lease is not None else None, default="missing", false_default="unknown")
    lease_agent_id = _recovery_field(_get(lease, "agent_id") if lease is not None else None, default=agent_id)
    lease_role = _role_text(_get(lease, "role") if lease is not None else None, default=role)
    lease_request_id = _recovery_field(_get(lease, "request_id") if lease is not None else None, default="")
    lease_request_hash = _recovery_field(_get(lease, "request_hash") if lease is not None else None, default=request_hash)
    item_state = _recovery_field(_get(item, "state") if item is not None else None, default="missing")
    item_claimed_by = _get(item, "claimed_by") if item is not None else None
    item_active_lease_id = _get(item, "active_lease_id") if item is not None else None

    recovery_outcome = "refresh_state"
    reason_code = "STALE_REQUEST_CONTEXT"
    if item is not None and (_get(item, "handled") or item_state == "handled"):
        recovery_outcome = "already_completed"
        reason_code = "LEASE_ALREADY_COMPLETED"
    elif lease_status == "accepted":
        recovery_outcome = "already_completed"
        reason_code = "LEASE_ALREADY_COMPLETED"
    elif lease is not None and (lease_agent_id != str(agent_id) or lease_role != str(role)):
        recovery_outcome = "stop"
        reason_code = "LEASE_RECOVERY_STOP"
    elif item_active_lease_id and str(item_active_lease_id) != str(lease_id):
        recovery_outcome = "stop"
        reason_code = "LEASE_RECOVERY_STOP"
    elif item_claimed_by and str(item_claimed_by) != str(agent_id):
        recovery_outcome = "stop"
        reason_code = "LEASE_RECOVERY_STOP"
    elif lease_status == "active" and lease_request_hash != str(request_hash):
        recovery_outcome = "refresh_state"
        reason_code = "STALE_REQUEST_CONTEXT"
    elif lease_status == "active" and lease is not None and _is_expired(lease, now):
        recovery_outcome = "renew"
        reason_code = "EXPIRED_LEASE_RENEWABLE"
    elif lease_status == "expired" and item_state in {"open", "claimed"}:
        recovery_outcome = "reclaim"
        reason_code = "EXPIRED_LEASE_RECLAIMABLE"
    elif lease_status in {"rejected", "released"}:
        recovery_outcome = "reclaim" if item_state == "open" else "refresh_state"
        reason_code = "EXPIRED_LEASE_RECLAIMABLE" if recovery_outcome == "reclaim" else "STALE_REQUEST_CONTEXT"
    elif lease_status == "active":
        recovery_outcome = "stop"
        reason_code = "LEASE_ACTIVE"
    elif lease_status not in {"active", "submitted"}:
        recovery_outcome = "stop"
        reason_code = "LEASE_RECOVERY_STOP"

    resume_command = (
        _lease_recovery_resume_command(session, lease_item_id, role=role, agent_id=agent_id)
        if recovery_outcome in {"reclaim", "refresh_state", "renew"}
        else None
    )
    recovery = LeaseRecoveryState(
        lease_id=str(lease_id),
        item_id=lease_item_id,
        agent_id=lease_agent_id,
        request_id=lease_request_id,
        request_hash=lease_request_hash,
        lease_status=lease_status,
        item_state=item_state,
        recovery_outcome=recovery_outcome,
        reason_code=reason_code,
        resume_command=resume_command,
    )
    return recovery


def calculate_conflict_keys(item: Any) -> tuple[str, ...]:
    keys: set[str] = set()

    item_id = _get(item, "item_id")
    if item_id:
        keys.add(f"item:{item_id}")

    path = _get(item, "path")
    hunk_key = _hunk_conflict_key(item)
    if path:
        if hunk_key:
            keys.add(hunk_key)
        else:
            keys.add(f"file:{_normalize_repo_path(path)}")

    for key in _get(item, "conflict_keys", ()) or ():
        if key:
            keys.add(str(key))

    thread_id = _get(item, "thread_id") or _get(item, "github_thread_id") or _get(item, "remote_thread_id")
    if thread_id:
        keys.add(f"thread:{thread_id}")
        if _get(item, "item_kind") == "github_thread":
            keys.add(f"github_reply:{thread_id}")
            keys.add(f"github_resolve:{thread_id}")

    return tuple(sorted(keys))


def _hunk_conflict_key(item: Any) -> str | None:
    path = _get(item, "path")
    if not path:
        return None
    start = _coerce_positive_int(
        _get(item, "start_line")
        or _get(item, "line")
        or _get(item, "original_line")
    )
    end = _coerce_positive_int(
        _get(item, "end_line")
        or _get(item, "original_end_line")
        or _get(item, "line")
        or _get(item, "original_line")
    )
    if start is None or end is None:
        return None
    if end < start:
        start, end = end, start
    return f"hunk:{_normalize_repo_path(path)}:{start}-{end}"


def _coerce_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _hunk_overlap(candidate_keys: tuple[str, ...], existing_keys: set[str]) -> set[str]:
    overlaps: set[str] = set()
    candidate_files = {key.removeprefix("file:") for key in candidate_keys if key.startswith("file:")}
    existing_files = {key.removeprefix("file:") for key in existing_keys if key.startswith("file:")}
    candidate_hunks = []
    for key in candidate_keys:
        parsed = _parse_hunk_key(key)
        if parsed is None:
            continue
        candidate_hunks.append(parsed)
        if parsed[0] in existing_files:
            overlaps.add(key)
    existing_hunks = []
    for key in existing_keys:
        parsed = _parse_hunk_key(key)
        if parsed is None:
            continue
        existing_hunks.append(parsed)
        if parsed[0] in candidate_files:
            overlaps.add(key)
    for candidate in candidate_hunks:
        candidate_path, candidate_start, candidate_end = candidate
        for existing in existing_hunks:
            existing_path, existing_start, existing_end = existing
            if candidate_path != existing_path:
                continue
            if candidate_start <= existing_end and existing_start <= candidate_end:
                overlaps.add(f"hunk:{candidate_path}:{max(candidate_start, existing_start)}-{min(candidate_end, existing_end)}")
    return overlaps


def _parse_hunk_key(key: str) -> tuple[str, int, int] | None:
    if not key.startswith("hunk:"):
        return None
    body = key.removeprefix("hunk:")
    path, separator, range_text = body.rpartition(":")
    if not separator:
        return None
    start_text, dash, end_text = range_text.partition("-")
    if not dash:
        return None
    start = _coerce_positive_int(start_text)
    end = _coerce_positive_int(end_text)
    if start is None or end is None:
        return None
    return path, start, end


def is_read_only_role(role: str | None) -> bool:
    return role in READ_ONLY_ROLES


def _same_agent_github_thread_file_overlap_allowed(
    existing: Any,
    *,
    agent_id: str,
    role: str,
    overlap: set[str],
    allow: bool,
) -> bool:
    if not allow:
        return False
    if role != "fixer" or _get(existing, "role") != role:
        return False
    if _get(existing, "agent_id") != agent_id:
        return False
    if not overlap or any(not (key.startswith("file:") or key.startswith("hunk:")) for key in overlap):
        return False
    existing_keys = set(_conflict_keys(existing))
    return any(key.startswith("github_reply:") for key in existing_keys) and any(
        key.startswith("github_resolve:") for key in existing_keys
    )


def _make_lease(**kwargs: Any) -> Any:
    return ClaimLease(**kwargs)


def _expire_lease(session: Any, lease: Any, now: datetime) -> None:
    _set(lease, "status", "expired")
    _set(lease, "completed_at", now)
    _return_expired_items_to_open(session, [lease])
    item = _items(session).get(str(_get(lease, "item_id") or ""))
    if isinstance(item, dict) and item.get("state") == "claimed":
        active_lease_id = item.get("active_lease_id")
        claimed_by = item.get("claimed_by")
        if active_lease_id in (None, _get(lease, "lease_id")) and claimed_by in (None, _get(lease, "agent_id")):
            item["state"] = "open"
            item["claimed_by"] = None
            item["claimed_at"] = None
            item["lease_expires_at"] = None
            item.pop("active_lease_id", None)
    _append_lease_event(session, lease, "lease_expired", now=now)


def _recovery_field(value: Any, *, default: Any, false_default: Any | None = None) -> str:
    if value is None or value == "":
        return str(default)
    if isinstance(value, bool) and value is False:
        return str(default if false_default is None else false_default)
    return str(value)


def _role_text(value: Any, *, default: Any) -> str:
    if value is None or value == "":
        return str(default)
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _is_expired(lease: Any, now: datetime) -> bool:
    return _get(lease, "expires_at") <= now


def _find_lease(session: Any, lease_id: str) -> Any:
    try:
        return _leases(session)[lease_id]
    except KeyError as exc:
        raise LeaseSubmissionError("LEASE_NOT_FOUND", lease_id) from exc


def _raise_submission_error(
    session: Any,
    reason_code: str,
    detail: str,
    *,
    lease: Any,
    agent_id: str,
    role: str,
    item_id: str,
    request_hash: str,
    now: datetime,
) -> None:
    recovery = calculate_lease_recovery_state(
        session,
        str(_get(lease, "lease_id") or detail),
        agent_id=agent_id,
        role=role,
        item_id=item_id,
        request_hash=request_hash,
        now=now,
    ).to_dict()
    _append_lease_recovery_event(session, recovery, now=now)
    raise LeaseSubmissionError(reason_code, detail, recovery_state=recovery)


def _items(session: Any) -> dict[str, Any]:
    if isinstance(session, dict):
        return session.setdefault("items", {})
    items = getattr(session, "items", None)
    if items is None:
        items = {}
        setattr(session, "items", items)
    return items


def _leases(session: Any) -> dict[str, Any]:
    if isinstance(session, dict):
        return session.setdefault("leases", {})
    leases = getattr(session, "leases", None)
    if leases is None:
        leases = {}
        setattr(session, "leases", leases)
    return leases


def _lease_events(session: Any) -> list[dict[str, Any]]:
    if isinstance(session, dict):
        return session.setdefault("lease_events", [])
    events = getattr(session, "lease_events", None)
    if events is None:
        events = []
        setattr(session, "lease_events", events)
    return events


def _append_lease_event(
    session: Any,
    lease: Any,
    event_type: str,
    *,
    now: datetime,
    reason: str | None = None,
) -> None:
    event = {
        "event_type": event_type,
        "timestamp": now.isoformat(),
        "lease_id": _get(lease, "lease_id"),
        "item_id": _get(lease, "item_id"),
        "agent_id": _get(lease, "agent_id"),
        "role": _get(lease, "role"),
        "status": _get(lease, "status"),
    }
    if reason is not None:
        event["reason"] = reason
    _lease_events(session).append(event)


def _append_lease_recovery_event(session: Any, recovery: dict[str, Any], *, now: datetime) -> None:
    event = {
        "event_type": "lease_recovery_calculated",
        "timestamp": now.isoformat(),
        "lease_id": recovery["lease_id"],
        "item_id": recovery["item_id"],
        "agent_id": recovery["agent_id"],
        "status": recovery["lease_status"],
        "recovery_outcome": recovery["recovery_outcome"],
        "reason_code": recovery["reason_code"],
    }
    _lease_events(session).append(event)


def _lease_recovery_resume_command(session: Any, item_id: str, *, role: str, agent_id: str) -> str:
    repo = _get(session, "repo") or "<owner/repo>"
    pr_number = _get(session, "pr_number") or "<pr_number>"
    return f"gh-address-cr agent next {repo} {pr_number} --role {role} --agent-id {agent_id} --item-id {item_id}"


def _conflict_keys(lease: Any) -> set[str]:
    return set(_get(lease, "conflict_keys", ()) or ())


def _required(value: Any, field_name: str) -> Any:
    if value in (None, ""):
        raise ValueError(f"{field_name} is required")
    return value


def _normalize_repo_path(path: Any) -> str:
    normalized = posixpath.normpath(str(path).replace("\\", "/"))
    if normalized == ".":
        return ""
    return normalized.removeprefix("./").lstrip("/")
