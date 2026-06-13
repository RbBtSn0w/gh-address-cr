from __future__ import annotations

from collections.abc import Mapping
from typing import Any

GITHUB_THREAD_CLAIMABLE_STATES = frozenset({"open", "blocked", "waiting_for_fix", "stale"})
GITHUB_THREAD_TERMINAL_STATES = frozenset(
    {
        "closed",
        "fixed",
        "clarified",
        "deferred",
        "rejected",
        "resolved",
        "verified",
        "published",
    }
)


def normalized_thread_state(row: Mapping[str, Any]) -> str:
    state = str(row.get("state") or "").strip().lower()
    if state:
        return state
    status = str(row.get("status") or "").strip().lower()
    if status == "closed":
        return "closed"
    if status == "stale":
        return "stale"
    return status


def is_github_thread_item(row: Mapping[str, Any]) -> bool:
    return str(row.get("item_kind") or row.get("kind") or "").lower() == "github_thread"


def is_resolved_github_thread(row: Mapping[str, Any]) -> bool:
    if "isResolved" in row:
        return bool(row["isResolved"])
    if "is_resolved" in row:
        return bool(row["is_resolved"])
    return normalized_thread_state(row) in GITHUB_THREAD_TERMINAL_STATES


def is_stale_or_outdated_github_thread(row: Mapping[str, Any]) -> bool:
    state = normalized_thread_state(row)
    status = str(row.get("status") or "").strip().upper()
    return state == "stale" or status == "STALE" or bool(row.get("is_outdated") or row.get("isOutdated"))


def is_stale_github_thread_item(row: Mapping[str, Any]) -> bool:
    return is_github_thread_item(row) and is_stale_or_outdated_github_thread(row)


def is_terminal_github_thread(row: Mapping[str, Any]) -> bool:
    return normalized_thread_state(row) in GITHUB_THREAD_TERMINAL_STATES


def is_claimable_github_thread(row: Mapping[str, Any], *, require_item_kind: bool = True) -> bool:
    if require_item_kind and not is_github_thread_item(row):
        return False
    if is_resolved_github_thread(row):
        return False
    state = normalized_thread_state(row) or ("stale" if is_stale_or_outdated_github_thread(row) else "open")
    return state in GITHUB_THREAD_CLAIMABLE_STATES


def returned_claimable_state(row: Mapping[str, Any]) -> tuple[str, str]:
    if is_stale_or_outdated_github_thread(row):
        return "stale", "STALE"
    return "open", "OPEN"
