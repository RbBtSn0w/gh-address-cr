"""Command handlers."""

from __future__ import annotations

from typing import Any

from app.threads import reopen_resolved_thread_for_reply


def reply_to_closed_thread(session: dict[str, Any], item_id: str, agent_id: str) -> dict[str, Any]:
    reopen_resolved_thread_for_reply(session, item_id=item_id, agent_id=agent_id)
    session["claimed_by"] = agent_id
    return session["items"][item_id]
