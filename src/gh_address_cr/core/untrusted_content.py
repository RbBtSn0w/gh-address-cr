"""Projection of session items into the agent-facing ActionRequest shape.

Reviewer comment bodies and producer finding text are third-party writable. Flat
alongside machine fields they read as peers of `item_id`/`thread_id`; behind a
named envelope the boundary is part of the payload instead of prose in SKILL.md.

Only the request projection changes. Session items keep their flat `body`, which
the trivial-fix safety gates, local-finding fingerprint, batch matching, and
severity extraction all depend on.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

GITHUB_REVIEW_THREAD_SOURCE = "github_review_thread"
LOCAL_FINDING_SOURCE = "local_finding_producer"


def untrusted_content_envelope(item: Mapping[str, Any]) -> dict[str, Any]:
    """Build the envelope carrying an item's third-party-authored text."""
    is_github_thread = str(item.get("item_kind") or "") == "github_thread"
    envelope: dict[str, Any] = {
        "source": GITHUB_REVIEW_THREAD_SOURCE if is_github_thread else LOCAL_FINDING_SOURCE,
        "body": str(item.get("body") or ""),
    }
    author_login = item.get("first_author_login") or item.get("latest_author_login")
    if author_login:
        envelope["author_login"] = str(author_login)
    elif not is_github_thread and item.get("source"):
        envelope["producer"] = str(item["source"])
    return envelope


def request_item_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    """Project a session item for an ActionRequest, moving `body` behind the envelope."""
    projected = dict(item)
    projected.pop("body", None)
    projected["untrusted_content"] = untrusted_content_envelope(item)
    return projected
