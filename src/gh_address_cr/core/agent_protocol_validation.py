"""Validation-command normalization/telemetry and response-field validators.

Extracted from agent_protocol.py: this is the leaf cluster of the agent
protocol — parsing and validating individual response fields, with no
dependency on session/lease state beyond what callers pass in. Shared by
agent_protocol.py, workflow.py, workflow_matching.py, and commands/agent.py.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.severity import first_scene_item_severity
from gh_address_cr.core.utils import (
    normalize_optional_fix_reply_severity as _normalize_optional_fix_reply_severity,
)
from gh_address_cr.core.utils import (
    severity_override_note as _severity_override_note,
)
from gh_address_cr.core.validation_evidence import validation_result_is_success


def record_validation_command_telemetry(
    session: dict[str, Any],
    validation_cmds: Any,
    *,
    seen: set[tuple[str, str, str, str, str, str]] | None = None,
) -> None:
    if not isinstance(validation_cmds, list):
        return
    try:
        import shlex
        import time

        from gh_address_cr.core.telemetry import SessionTelemetry
        from gh_address_cr.core.telemetry_safety import command_label, is_inline_env_assignment

        telemetry = SessionTelemetry.get_instance()
    except Exception:
        return

    if seen is None:
        seen = set()

    for val_cmd in normalize_validation_command_records(validation_cmds):
        try:
            cmd_name = val_cmd.get("command")
            if not isinstance(cmd_name, str):
                continue
            try:
                argv = shlex.split(cmd_name)
            except ValueError:
                continue
            while argv and is_inline_env_assignment(argv[0]):
                argv.pop(0)
            if not argv:
                continue
            cmd_label = command_label(argv)
            dedupe_key = (
                cmd_label,
                _validation_command_fingerprint(cmd_name),
                _dedupe_value(val_cmd.get("result")),
                _dedupe_value(val_cmd.get("duration")),
                _dedupe_value(val_cmd.get("start_time")),
                _dedupe_value(val_cmd.get("end_time")),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            exit_code = _validation_result_exit_code(val_cmd.get("result"))
            dur = val_cmd.get("duration")
            start = val_cmd.get("start_time")
            end = val_cmd.get("end_time")

            if start is not None and end is not None:
                start_val = float(start)
                end_val = float(end)
            elif dur is not None:
                end_val = time.time()
                start_val = end_val - float(dur)
            else:
                end_val = time.time()
                start_val = end_val

            telemetry.record(
                command=cmd_label,
                start_time=start_val,
                end_time=end_val,
                exit_code=exit_code,
            )
        except Exception:
            continue


def _dedupe_value(value: Any) -> str:
    return "" if value is None else str(value)


def _validation_command_fingerprint(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest()


def _validation_result_exit_code(result: Any) -> int:
    return 0 if validation_result_is_success(result) else 1


def normalize_validation_command_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    commands: list[dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, dict):
            command = str(entry.get("command") or "").strip()
            result = str(entry.get("result") or "").strip()
            summary = str(entry.get("summary") or "").strip()
            duration = entry.get("duration")
            start_time = entry.get("start_time")
            end_time = entry.get("end_time")
        else:
            raw = str(entry or "").strip()
            command, result, duration = split_validation_command_record(raw)
            summary = ""
            start_time = None
            end_time = None
        if not command or not result:
            continue
        row: dict[str, Any] = {"command": command, "result": result}
        if summary:
            row["summary"] = summary
        if duration is not None:
            row["duration"] = duration
        if start_time is not None:
            row["start_time"] = start_time
        if end_time is not None:
            row["end_time"] = end_time
        commands.append(row)
    return commands


_VALIDATION_DURATION_SUFFIX_RE = re.compile(r"@(\d+(?:\.\d+)?)(ms|s)$")


def _strip_validation_duration_suffix(value: str) -> tuple[str, float | None]:
    """Split a trailing ``@<n>ms``/``@<n>s`` timing suffix off a validation result token.

    Returns ``(token_without_suffix, duration_seconds_or_None)``. Durations are
    normalized to seconds to match the existing validation ``duration`` contract.
    """
    stripped = value.strip()
    match = _VALIDATION_DURATION_SUFFIX_RE.search(stripped)
    if match is None:
        return value, None
    number = float(match.group(1))
    seconds = number / 1000.0 if match.group(2) == "ms" else number
    return stripped[: match.start()], seconds


def split_validation_command_record(raw: str) -> tuple[str, str, float | None]:
    command, separator, result = raw.rpartition("=")
    result_token, duration = _strip_validation_duration_suffix(result)
    if not separator or not _looks_like_validation_result(result_token):
        return raw.strip(), "passed", None
    return command.strip(), result_token.strip(), duration


def _looks_like_validation_result(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized or any(char.isspace() for char in normalized):
        return False
    return normalized in {"pass", "passed", "success", "succeeded", "ok", "fail", "failed", "error", "skipped"}


def validate_requested_severity(
    value: Any,
    *,
    status: str,
    waiting_on: str,
    payload: dict[str, Any] | None = None,
) -> str | None:
    if value in (None, ""):
        return None
    normalized = _normalize_optional_fix_reply_severity(value)
    if normalized:
        return normalized
    raise WorkflowError(
        status=status,
        reason_code="INVALID_FIX_REPLY_SEVERITY",
        waiting_on=waiting_on,
        exit_code=2,
        message="Explicit severity override must be one of P0, P1, P2, P3, or P4.",
        payload=payload or {},
    )


def validate_severity_override_note(
    severity: str,
    item: dict[str, Any],
    note: str | None,
    *,
    status: str,
    waiting_on: str,
    payload: dict[str, Any] | None = None,
) -> None:
    first_scene_severity = first_scene_item_severity(item)
    if not first_scene_severity or first_scene_severity == severity:
        return
    if _severity_override_note(note):
        return
    raise WorkflowError(
        status=status,
        reason_code="SEVERITY_OVERRIDE_NOTE_REQUIRED",
        waiting_on=waiting_on,
        exit_code=2,
        message=(
            f"Explicit severity override {severity} conflicts with first-scene severity "
            f"{first_scene_severity}; add a severity note explaining the override."
        ),
        payload=payload or {},
    )
