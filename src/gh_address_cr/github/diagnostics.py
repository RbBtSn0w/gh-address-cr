from __future__ import annotations

from collections.abc import Mapping
import re
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
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TOKEN_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.IGNORECASE),
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b((?:[A-Za-z0-9]+[_-])*token|secret|password|api[_-]?key)\b([=: ]+)([^\s,;&]+)"
)
PRIVATE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(username|user|email|hostname|host|machine|machine_name|computer|computer_name)\b([=: ]+)([^\s,;&]+)"
)


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
        diagnostics["stderr_excerpt"] = _excerpt(_redact_diagnostic_text(detail))
    return diagnostics


def github_waiting_on(diagnostics: Mapping[str, Any] | None) -> str:
    category = diagnostics.get("stderr_category") if isinstance(diagnostics, Mapping) else None
    if category == "auth":
        return "github_auth"
    if category == "network":
        return "github_network"
    if category in {"environment", "sandbox"}:
        return "github_environment"
    if category == "rate_limit":
        return "github_rate_limit"
    return "github"


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


def _redact_diagnostic_text(value: str) -> str:
    redacted = EMAIL_RE.sub("[redacted-email]", value)
    for pattern in TOKEN_PATTERNS:
        redacted = pattern.sub("[redacted-token]", redacted)
    redacted = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted-token]", redacted)
    return PRIVATE_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", redacted)
