"""Whether a commit cited in a fix reply belongs to the pull request (Spec 039 R3)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# Git's minimum abbreviation length.
MIN_COMMIT_PREFIX = 4


def cited_commit(response: dict[str, Any]) -> str:
    fix_reply = response.get("fix_reply")
    if not isinstance(fix_reply, dict):
        return ""
    return str(fix_reply.get("commit_hash") or "").strip()


def commit_in_pr(commit: str, pr_commit_shas: Iterable[str]) -> bool:
    """A full SHA or an abbreviation of at least four characters matches."""
    prefix = commit.strip().lower()
    if len(prefix) < MIN_COMMIT_PREFIX:
        return False
    return any(sha.lower().startswith(prefix) for sha in pr_commit_shas)
