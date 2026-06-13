"""Pure helpers for deciding whether validation evidence proves success.

Single source of truth so the logic-validation signal and the final-gate
projection cannot drift. Zero imports beyond typing to avoid cycles.
"""

from __future__ import annotations

from typing import Any

# A validation result counts as success only when it starts with one of these.
# An absent/empty result defaults to "passed", matching the agent CLI default
# (`<command>` with no `=result` suffix is treated as passed).
VALIDATION_SUCCESS_PREFIXES = ("passed", "pass", "success", "succeeded", "ok")


def validation_result_is_success(result: Any) -> bool:
    """True when an explicit (or defaulted) validation result is success-like."""
    normalized = str(result or "passed").strip().lower()
    return normalized.startswith(VALIDATION_SUCCESS_PREFIXES)


def validation_evidence_has_success(value: Any) -> bool:
    """True when `value` carries at least one success-like validation record.

    Unlike a bare non-empty check, an explicit failing result (e.g.
    ``{"command": "pytest", "result": "failed"}``) does NOT count as evidence,
    so a terminal item cannot satisfy the gate with failing validation logs.
    A bare command string (no result) keeps the system default of "passed".
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        if "command" in value or "result" in value or "exit_code" in value:
            exit_code = value.get("exit_code")
            if exit_code is not None:
                try:
                    if int(exit_code) != 0:
                        return False
                except (TypeError, ValueError):
                    pass
            return validation_result_is_success(value.get("result"))
        return any(validation_evidence_has_success(inner) for inner in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(validation_evidence_has_success(inner) for inner in value)
    return bool(value)
