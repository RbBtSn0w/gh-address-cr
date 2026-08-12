from __future__ import annotations

NETWORK_TRANSIENT_MARKERS = (
    "error connecting",
    "failed to connect",
    "temporary failure",
    "timeout",
    "timed out",
    "connection reset",
)

TRANSIENT_GITHUB_FAILURE_MARKERS = (
    "502",
    "503",
    *NETWORK_TRANSIENT_MARKERS,
    "graphql error",
    "graphql failed",
)


def is_transient_github_failure_text(*parts: str | None) -> bool:
    text = "\n".join(part or "" for part in parts).lower()
    return any(marker in text for marker in TRANSIENT_GITHUB_FAILURE_MARKERS)
