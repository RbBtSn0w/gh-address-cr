"""How to read a `gh pr checks --json` result (Spec 039 ACT-02).

`gh pr checks` uses non-zero exits for PR states: 8 while checks are pending, and
1 both for failed checks (JSON on stdout) and for a PR with no check runs at all
(empty stdout, message on stderr). Authentication and network errors also exit 1,
so the stdout/stderr shape decides, and the runtime and its telemetry share this rule.
"""

from __future__ import annotations

import re

# `gh pr checks` says "no checks reported", or "no required checks reported" with --required.
NO_CHECKS_PATTERN = re.compile(r"no (required )?checks reported")


def pr_checks_result(returncode: int, stdout: str | None, stderr: str | None) -> str:
    """Return `checks`, `no_checks`, or `error`."""
    has_payload = bool((stdout or "").strip())
    if returncode == 0 or (returncode in {1, 8} and has_payload):
        return "checks"
    if returncode == 1 and NO_CHECKS_PATTERN.search((stderr or "").lower()):
        return "no_checks"
    return "error"


def is_pr_checks_command(cmd: list[str]) -> bool:
    if len(cmd) < 3 or cmd[1:3] != ["pr", "checks"]:
        return False
    # Accept POSIX and Windows paths, and a case-insensitive `.exe` suffix.
    executable = re.split(r"[\\/]", cmd[0])[-1].lower()
    return executable in {"gh", "gh.exe"}
