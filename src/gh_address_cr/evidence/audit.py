from __future__ import annotations

from typing import Any


TERMINAL_ITEM_STATES = {"fixed", "clarified", "deferred", "rejected", "closed", "CLOSED"}


def has_durable_reply_evidence(item: dict[str, Any] | None) -> bool:
    if not isinstance(item, dict):
        return False
    evidence = item.get("reply_evidence")
    if isinstance(evidence, dict):
        reply_url = evidence.get("reply_url")
        author_login = evidence.get("author_login")
        return isinstance(reply_url, str) and bool(reply_url.strip()) and isinstance(author_login, str) and bool(author_login.strip())

    reply_url = item.get("reply_url")
    return bool(item.get("reply_posted")) and isinstance(reply_url, str) and bool(reply_url.strip())


def terminal_threads_missing_reply_evidence(items: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for item in items:
        if item.get("item_kind") != "github_thread":
            continue
        if item.get("state") not in TERMINAL_ITEM_STATES:
            continue
        if not has_durable_reply_evidence(item):
            missing.append(str(item.get("item_id") or ""))
    return [item_id for item_id in missing if item_id]


def resolve_guard_error(
    *,
    reply_evidence: dict[str, Any] | None,
    reply_body: str | None = None,
    durable_reply_required: bool = True,
) -> str | None:
    if reply_body and reply_body.strip():
        return None
    if not durable_reply_required:
        return None
    item = {"reply_evidence": reply_evidence}
    if has_durable_reply_evidence(item):
        return None
    return "GitHub resolve requires durable reply evidence before mutation."
