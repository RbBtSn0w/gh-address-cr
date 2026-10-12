from __future__ import annotations

import random
import re

NETWORK_TRANSIENT_MARKERS = (
    "error connecting",
    "failed to connect",
    "temporary failure",
    "timeout",
    "timed out",
    "connection reset",
)

TRANSIENT_GITHUB_FAILURE_MARKERS = (
    "bad gateway",
    "service unavailable",
    "gateway time-out",
    "gateway timeout",
    *NETWORK_TRANSIENT_MARKERS,
    "graphql error",
    "graphql failed",
)

# Anchored so a bare "500"/"502" inside a node id, path or number does not match.
_TRANSIENT_HTTP_STATUS_RE = re.compile(r"(?<![\w/.-])50[0234](?![\w/.-])")


def is_transient_github_failure_text(*parts: str | None) -> bool:
    text = "\n".join(part or "" for part in parts).lower()
    if _TRANSIENT_HTTP_STATUS_RE.search(text):
        return True
    return any(marker in text for marker in TRANSIENT_GITHUB_FAILURE_MARKERS)


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter so concurrent sessions do not retry in lockstep."""
    return (2**attempt) * random.uniform(0.5, 1.0)
