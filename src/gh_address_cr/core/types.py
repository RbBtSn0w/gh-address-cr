from __future__ import annotations

from typing import Any, TypedDict


class Finding(TypedDict, total=False):
    path: str
    line: int
    title: str
    body: str
    source: str
    severity: str
    confidence: float


class Item(TypedDict, total=False):
    item_id: str
    item_kind: str
    source: str
    title: str
    body: str
    path: str
    line: int
    status: str
    state: str
    blocking: bool
    handled: bool
    claimed_by: str | None
    claimed_at: str | None
    lease_expires_at: str | None
    metadata: dict[str, Any]


class Lease(TypedDict, total=False):
    lease_id: str
    item_id: str
    agent_id: str
    role: str
    status: str
    created_at: str
    expires_at: str
    request_id: str
    request_hash: str
    conflict_keys: list[str]


class Session(TypedDict, total=False):
    session_id: str
    repo: str
    pr_number: str
    status: str
    items: dict[str, Item]
    leases: dict[str, Lease]
    metadata: dict[str, Any]
