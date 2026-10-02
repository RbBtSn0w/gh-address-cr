"""Fixer-lease lookup and recovery helpers for the agent protocol.

Extracted from agent_protocol.py: pure lease lookup/derivation only — no
ledger writes here beyond the release side effect already owned by
core.leases, and no WorkflowError raising. Shared by agent_protocol.py's
submission pipeline (agent_protocol_submission.py) and agent_batch.py, which
use these as peers rather than one reaching into the other's internals.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from gh_address_cr.core import protocol_codes
from gh_address_cr.core.leases import calculate_lease_recovery_state, release_lease
from gh_address_cr.core.utils import coerce_now as _coerce_now
from gh_address_cr.core.utils import get_field as _get
from gh_address_cr.core.utils import get_session_items as _items
from gh_address_cr.core.utils import return_item_to_claimable_state as _return_item_to_claimable_state


def active_fixer_lease_for_item(
    session: dict[str, Any], item_id: str, *, agent_id: str | None = None
) -> dict[str, Any] | None:
    for lease in session.get("leases", {}).values():
        if not isinstance(lease, dict):
            continue
        if lease.get("item_id") != item_id:
            continue
        if lease.get("status") != "active":
            continue
        if lease.get("role") != "fixer":
            continue
        if agent_id is not None and lease.get("agent_id") != agent_id:
            continue
        return lease
    return None


def recover_rebound_github_thread_lease(
    session: dict[str, Any],
    response: dict[str, Any],
    *,
    item_id: str,
    current_lease_id: str | None = None,
) -> dict[str, Any] | None:
    normalized_item_id = item_id.strip()
    if not normalized_item_id:
        return None
    item = _items(session).get(normalized_item_id)
    if not isinstance(item, dict) or item.get("item_kind") != "github_thread":
        return None
    if str(response.get("resolution") or "") != "fix":
        return None
    state = str(item.get("state") or "").lower()
    if state not in {"stale", "claimed"} and not bool(item.get("is_outdated")):
        return None
    rebound_lease = active_fixer_lease_for_item(
        session,
        normalized_item_id,
        agent_id=str(response.get("agent_id") or ""),
    )
    if not isinstance(rebound_lease, dict):
        return None
    rebound_lease_id = str(_get(rebound_lease, "lease_id") or "")
    if not rebound_lease_id or rebound_lease_id == str(current_lease_id or ""):
        return None
    return {
        "lease_id": rebound_lease_id,
        "lease": rebound_lease,
        "item_id": normalized_item_id,
        "item": item,
    }


def release_irrecoverable_request_lease(
    session: dict[str, Any],
    prepared: dict[str, Any],
    *,
    now: datetime,
) -> None:
    lease = prepared["lease"]
    lease_id = str(prepared["lease_id"])
    if str(_get(lease, "status") or "") in {"active", "submitted"}:
        release_lease(session, lease_id, now=now, reason="stale_request_context")
    item = prepared["item"]
    active_lease_id = str(item.get("active_lease_id") or "")
    if active_lease_id and active_lease_id != lease_id:
        return
    _return_item_to_claimable_state(item)
    item["claimed_by"] = None
    item["claimed_at"] = None
    item["lease_expires_at"] = None
    item.pop("active_lease_id", None)


def lease_submission_rejection_reason(
    response: dict[str, Any],
    prepared: dict[str, Any],
    now: datetime,
) -> str | None:
    lease = prepared["lease"]
    status = str(_get(lease, "status") or "")
    if status == "submitted":
        return "DUPLICATE_SUBMISSION"
    if status in {"accepted", "rejected", "expired", "released"}:
        return "STALE_LEASE"
    if status != "active":
        return "STALE_LEASE"

    expires_at = _get(lease, "expires_at")
    if isinstance(expires_at, str):
        expires_at = _coerce_now(expires_at)
    if expires_at is not None and expires_at <= now:
        return "EXPIRED_LEASE"
    if str(_get(lease, "agent_id")) != str(response["agent_id"]):
        return "WRONG_AGENT"
    if str(_get(lease, "item_id")) != str(prepared["item_id"]):
        return "WRONG_ITEM"
    if str(_get(lease, "request_hash")) != str(prepared["expected_request_hash"]):
        return protocol_codes.STALE_REQUEST_CONTEXT
    return None


def lease_recovery_payload_for_response(
    session: dict[str, Any],
    response: dict[str, Any],
    lease: dict[str, Any],
    *,
    item_id: str,
    request_hash: str,
    now: datetime,
) -> dict[str, Any]:
    return calculate_lease_recovery_state(
        session,
        str(lease.get("lease_id") or response.get("lease_id") or ""),
        agent_id=str(response.get("agent_id") or lease.get("agent_id") or ""),
        role=str(lease.get("role") or ""),
        item_id=item_id,
        request_hash=request_hash,
        now=now,
    ).to_dict()


def payload_for_lease(
    path: Path,
    *,
    request_id: str,
    lease_id: str,
    validate: Any | None = None,
) -> dict[str, Any] | None:
    """The JSON object on disk when it belongs to this lease, else None.

    One predicate for the request and for its response skeleton. Applying it to the
    request only was an asymmetry, not a decision: a corrupt or foreign skeleton was
    handed back untouched while the request beside it would have been rebuilt.

    Usable means all of:

    - it parses, and is an object;
    - it passes `validate`, when one is given. For the request that is
      `ActionRequest.from_dict`, the parser submit itself uses, so what re-entry
      accepts cannot drift from what submit accepts. "Any JSON object" is not enough:
      `{}` parses, then skeleton generation indexes required keys and raises KeyError
      instead of rebuilding. A skeleton has no such parser -- it is deliberately
      incomplete until the agent fills it in -- so it is checked on identity alone;
    - it carries this lease's `request_id` and `lease_id`. A file can be perfectly
      valid and still belong to another lease, and handing that back points the agent
      at the wrong request.

    A skeleton the agent has already filled in still matches, so re-entry keeps it;
    only an unusable one is regenerated and the agent's evidence is never discarded.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if validate is not None:
            validate(payload)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None
    if str(payload.get("request_id")) != request_id or str(payload.get("lease_id")) != lease_id:
        return None
    return payload
