"""Review-thread session transitions."""

from __future__ import annotations

from typing import Any


def reopen_resolved_thread_for_reply(session: dict[str, Any], *, item_id: str, agent_id: str) -> None:
    """Make a thread resolved on GitHub without our reply claimable again.

    Only the threads final-gate blocks on qualify: resolved remotely, no reply
    evidence from this session. The emitted event stays low-cardinality.
    """
    item = session["items"][item_id]
    if not item.get("remote_resolved") or item.get("reply_url"):
        raise ValueError(f"{item_id} is not a resolved thread awaiting a reply")
    item["status"] = "OPEN"
    item["remote_resolved"] = False
    session.setdefault("events", []).append({"event": "thread_reopened_for_reply", "item_id": item_id})
