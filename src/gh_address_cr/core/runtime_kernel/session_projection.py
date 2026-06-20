"""Rebuild agent-applied session item state by folding the evidence ledger (#116).

External facts (intake findings, remote GitHub threads) seed the base item map.
Every agent-applied mutation is recorded as a durable ledger event first, so the
mutable portion of each item is a *projection* of that event stream and can be
replayed for crash recovery. `session.json` is therefore a rebuildable cache, not
the sole source of truth for agent deltas.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping

# Agent-path event types this fold understands, in causal order.
AGENT_EVENT_TYPES = (
    "classification_recorded",
    "response_accepted",
    "verification_rejected",
    "reply_posted",
    "thread_resolved",
    "response_published",
)


def apply_ledger_events(
    base_items: Mapping[str, Mapping[str, Any]],
    records: Iterable[Any],
) -> dict[str, dict[str, Any]]:
    """Fold ledger events onto a copy of `base_items` and return the result.

    `records` are `EvidenceRecord`-like objects with `event_type`, `item_id`, and
    `payload`. Records are applied in iteration order, which the ledger preserves
    as append order.
    """
    from gh_address_cr.core.agent_protocol import apply_response_to_item

    items: dict[str, dict[str, Any]] = {
        str(item_id): copy.deepcopy(dict(item)) for item_id, item in base_items.items()
    }

    for record in records:
        event_type = _attr(record, "event_type")
        item_id = str(_attr(record, "item_id") or "")
        payload = _attr(record, "payload") or {}
        item = items.get(item_id)
        if item is None:
            # Fail loud: a ledger event whose item is absent from the base map means
            # the cache and the durable ledger have diverged. Silently skipping it
            # (the old `continue`) would reconstruct a partial projection and quietly
            # weaken the crash-recovery guarantee this module promises (#137).
            raise ValueError(
                f"orphan ledger event references unknown item_id {item_id!r} "
                f"(event_type={event_type!r}); session base has {len(items)} item(s) — "
                "ledger/cache divergence breaks deterministic crash-recovery replay"
            )

        if event_type == "classification_recorded":
            classification = str(payload.get("classification") or "")
            if classification:
                item["classification_evidence"] = {
                    "event_type": "classification_recorded",
                    "classification": classification,
                    "note": payload.get("note"),
                    "record_id": _attr(record, "record_id"),
                }
                item["decision"] = classification
        elif event_type == "response_accepted":
            response = payload.get("response")
            if isinstance(response, Mapping):
                apply_response_to_item(item, dict(response))
                # `apply_response_to_item` stamps local-finding `handled_at` with
                # datetime.now(); pin it to the event's append time so a rebuild is
                # deterministic and does not overwrite the original timestamp.
                record_ts = _attr(record, "timestamp")
                if record_ts and item.get("handled_at"):
                    item["handled_at"] = record_ts
        elif event_type == "verification_rejected":
            # A verifier rejected a previously accepted fix: reopen the item so a
            # rebuild never reconstructs a rejected fix as terminal/handled (#117).
            item["state"] = "open"
            item["status"] = "OPEN"
            item["blocking"] = True
            item["handled"] = False
            item["thread_resolved"] = False
            note = payload.get("note")
            if note is not None:
                item["verification_rejection_note"] = note
        elif event_type == "reply_posted":
            reply_url = payload.get("reply_url")
            if reply_url:
                item["reply_posted"] = True
                item["reply_url"] = reply_url
                if not isinstance(item.get("reply_evidence"), dict):
                    item["reply_evidence"] = {}
                item["reply_evidence"]["reply_url"] = reply_url
        elif event_type == "thread_resolved":
            item["thread_resolved"] = True
        elif event_type == "response_published":
            item["state"] = "closed"
            item["status"] = "CLOSED"
            item["blocking"] = False
            item["handled"] = True
            item["thread_resolved"] = True
            item.pop("active_lease_id", None)

    return items


def rebuild_session_items(repo: str, pr_number: str, *, persist: bool = True) -> dict[str, Any]:
    """Reload a session and re-derive its items by folding the full ledger.

    Crash recovery: an event appended before a session-cache write is replayed
    here, restoring the cache to match the durable ledger. Re-applying events that
    are already reflected is idempotent, so this is safe to run at any time. When
    ``persist`` (default), the rebuilt `session.json` cache is written back so the
    recovery actually takes effect; pass ``persist=False`` for a dry read.
    """
    from gh_address_cr.core import session as session_store
    from gh_address_cr.core.utils import get_session_ledger

    session = session_store.load_session(repo, pr_number)
    ledger = get_session_ledger(session)
    base_items = session.get("items") if isinstance(session.get("items"), Mapping) else {}
    session["items"] = apply_ledger_events(base_items, ledger.load())
    if persist:
        session_store.save_session(repo, pr_number, session)
    return session


def _attr(record: Any, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    return getattr(record, name, None)
