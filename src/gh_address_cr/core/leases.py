from __future__ import annotations

import posixpath
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

try:
    from gh_address_cr.core.models import ClaimLease as _ModelClaimLease
except ImportError:
    _ModelClaimLease = None


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
    def __init__(self, reason_code: str, detail: str | None = None):
        self.reason_code = reason_code
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
        overlap = set(keys).intersection(_conflict_keys(existing))
        if overlap and not (is_read_only_role(role) and is_read_only_role(_get(existing, "role"))):
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
        raise LeaseSubmissionError("DUPLICATE_SUBMISSION", lease_id)
    if status in TERMINAL_LEASE_STATUSES:
        raise LeaseSubmissionError("STALE_LEASE", lease_id)
    if status != "active":
        raise LeaseSubmissionError("STALE_LEASE", lease_id)
    if _is_expired(lease, now):
        _expire_lease(session, lease, now)
        raise LeaseSubmissionError("EXPIRED_LEASE", lease_id)
    if _get(lease, "role") != role:
        raise LeaseSubmissionError("CROSS_ROLE_SUBMISSION", role)
    if _get(lease, "agent_id") != agent_id:
        raise LeaseSubmissionError("WRONG_AGENT", agent_id)
    if _get(lease, "item_id") != item_id:
        raise LeaseSubmissionError("WRONG_ITEM", item_id)
    if _get(lease, "request_hash") != request_hash:
        raise LeaseSubmissionError("STALE_REQUEST_CONTEXT", lease_id)

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


def calculate_conflict_keys(item: Any) -> tuple[str, ...]:
    keys: set[str] = set()

    item_id = _get(item, "item_id")
    if item_id:
        keys.add(f"item:{item_id}")

    path = _get(item, "path")
    if path:
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


def is_read_only_role(role: str | None) -> bool:
    return role in READ_ONLY_ROLES


def _make_lease(**kwargs: Any) -> Any:
    return ClaimLease(**kwargs)


def _expire_lease(session: Any, lease: Any, now: datetime) -> None:
    _set(lease, "status", "expired")
    _set(lease, "completed_at", now)
    _append_lease_event(session, lease, "lease_expired", now=now)


def _is_expired(lease: Any, now: datetime) -> bool:
    return _get(lease, "expires_at") <= now


def _find_lease(session: Any, lease_id: str) -> Any:
    try:
        return _leases(session)[lease_id]
    except KeyError as exc:
        raise LeaseSubmissionError("LEASE_NOT_FOUND", lease_id) from exc


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


def _conflict_keys(lease: Any) -> set[str]:
    return set(_get(lease, "conflict_keys", ()) or ())


def _required(value: Any, field_name: str) -> Any:
    if value in (None, ""):
        raise ValueError(f"{field_name} is required")
    return value


def _get(obj: Any, field: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _set(obj: Any, field: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[field] = value
    else:
        setattr(obj, field, value)


def _coerce_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _normalize_repo_path(path: Any) -> str:
    normalized = posixpath.normpath(str(path).replace("\\", "/"))
    if normalized == ".":
        return ""
    return normalized.removeprefix("./").lstrip("/")
