from __future__ import annotations

from typing import Any


AUTH_MARKERS = (
    "authentication",
    "gh auth login",
    "bad credentials",
    "not logged into",
    "not logged in",
    "401",
)
NETWORK_MARKERS = (
    "api.github.com",
    "could not resolve host",
    "failed to connect",
    "error connecting",
    "network is unreachable",
    "temporary failure",
    "connection reset",
    "timeout",
    "timed out",
)
SANDBOX_MARKERS = (
    "operation not permitted",
    "permission denied",
    "sandbox",
    "not permitted",
)
ENVIRONMENT_MARKERS = (
    "missing github cli",
    "`gh` on path",
    "executable file not found",
)
RATE_LIMIT_MARKERS = ("rate limit", "secondary rate")
NOT_FOUND_MARKERS = ("not found", "could not resolve to a node", "404")
API_MARKERS = ("graphql", "api")


def classify_github_failure(
    stderr: str | None,
    stdout: str | None = None,
    returncode: int | None = None,
    command: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    detail = (stderr or stdout or "").strip()
    text = detail.lower()
    category = _stderr_category(text)
    diagnostics: dict[str, Any] = {
        "stderr_category": category,
    }
    if command:
        diagnostics["command"] = [str(part) for part in command]
    if returncode is not None:
        diagnostics["returncode"] = returncode
    if detail:
        diagnostics["stderr_excerpt"] = _excerpt(detail)
    return diagnostics


def _stderr_category(text: str) -> str:
    if any(marker in text for marker in AUTH_MARKERS):
        return "auth"
    if any(marker in text for marker in SANDBOX_MARKERS):
        return "sandbox"
    if any(marker in text for marker in ENVIRONMENT_MARKERS):
        return "environment"
    if any(marker in text for marker in NETWORK_MARKERS):
        return "network"
    if any(marker in text for marker in RATE_LIMIT_MARKERS):
        return "rate_limit"
    if any(marker in text for marker in NOT_FOUND_MARKERS):
        return "not_found"
    if any(marker in text for marker in API_MARKERS):
        return "api"
    return "unknown"


def _excerpt(value: str, *, limit: int = 500) -> str:
    one_line = " ".join(value.split())
    if len(one_line) <= limit:
        return one_line
    return f"{one_line[: limit - 3]}..."
