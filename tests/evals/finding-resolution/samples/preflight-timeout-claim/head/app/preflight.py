"""`gh auth status` preflight run before every PR-scoped command."""

from __future__ import annotations

import random
import subprocess
import time

_PREFLIGHT_AUTH_ATTEMPTS = 2
_PREFLIGHT_AUTH_TIMEOUT_SECONDS = 30.0
_TRANSIENT_MARKERS = ("timed out", "connection reset", "502 bad gateway", "503 service unavailable")


def backoff_seconds(attempt: int) -> float:
    return min(4.0, 0.5 * 2**attempt) * random.uniform(0.5, 1.0)


def is_transient_failure(stderr: str | None, stdout: str | None) -> bool:
    text = f"{stderr or ''}\n{stdout or ''}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def run_gh_auth_status(auth_command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the auth preflight with a timeout and one jittered retry on transient failures."""
    attempt = 0
    while True:
        try:
            result = subprocess.run(
                auth_command, text=True, capture_output=True, timeout=_PREFLIGHT_AUTH_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(
                auth_command, 124, "", f"Command timed out after {_PREFLIGHT_AUTH_TIMEOUT_SECONDS} seconds."
            )
        attempt += 1
        if (
            result.returncode == 0
            or attempt >= _PREFLIGHT_AUTH_ATTEMPTS
            or not is_transient_failure(result.stderr, result.stdout)
        ):
            return result
        time.sleep(backoff_seconds(attempt - 1))
