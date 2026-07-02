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

# Result tokens we recognise as an explicit pass/fail verdict on a `<cmd>=<result>`
# string. Only a trailing token in this set is treated as a result, so commands
# that contain `=` internally (e.g. `VAR=val ./cmd`) are not misparsed.
KNOWN_VALIDATION_RESULT_TOKENS = frozenset(
    {"passed", "pass", "success", "succeeded", "ok", "failed", "fail", "failure", "error", "skipped"}
)


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
    if not value:
        if type(value) is str or isinstance(value, str):
            return False
        return False if value is None else bool(value)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        _command, separator, result = text.rpartition("=")
        if separator and result.strip().lower() in KNOWN_VALIDATION_RESULT_TOKENS:
            return validation_result_is_success(result)
        return True

    if isinstance(value, dict):
        return _check_dict_evidence(value)

    if isinstance(value, (list, tuple, set)):
        for inner in value:
            if validation_evidence_has_success(inner):
                return True
        return False

    return True


def _check_dict_evidence(value: dict) -> bool:
    if "command" in value or "result" in value or "exit_code" in value:
        exit_code = value.get("exit_code")
        if exit_code is not None:
            try:
                if int(exit_code) != 0:
                    return False
            except (TypeError, ValueError):
                pass
        return validation_result_is_success(value.get("result"))
    for inner in value.values():
        if validation_evidence_has_success(inner):
            return True
    return False
