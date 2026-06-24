from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from gh_address_cr.core import session as session_store
from gh_address_cr.core.errors import WorkflowError
from gh_address_cr.core.github_thread_state import returned_claimable_state
from gh_address_cr.core.severity import first_scene_item_severity, normalize_severity
from gh_address_cr.evidence.ledger import EvidenceLedger


def get_field(obj: Any, field: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def set_field(obj: Any, field: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[field] = value
    else:
        setattr(obj, field, value)


def coerce_now(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 string to a timezone-aware UTC datetime, or None.

    Naive timestamps are coerced to UTC and aware timestamps are converted to
    UTC so mixing naive and aware values never raises ``TypeError`` on
    comparison or subtraction, and the returned tzinfo is always UTC.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_ready(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(inner) for inner in value]
    if hasattr(value, "__dict__"):
        return json_ready(vars(value))
    return value


def get_session_items(session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = session.setdefault("items", {})
    if isinstance(items, dict):
        return {str(key): value for key, value in items.items() if isinstance(value, dict)}
    raise WorkflowError(
        status="INVALID_SESSION",
        reason_code="INVALID_ITEMS_SHAPE",
        waiting_on="session",
        exit_code=5,
        message="Session items must be a JSON object.",
    )


def get_session_ledger(session: dict[str, Any]) -> EvidenceLedger:
    return EvidenceLedger(
        session.get("ledger_path") or session_store.default_ledger_path(str(session["repo"]), str(session["pr_number"]))
    )


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def normalize_validation_commands(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    commands: list[str] = []
    for entry in value:
        command = entry.get("command") if isinstance(entry, dict) else entry
        command_text = str(command or "").strip()
        if command_text:
            commands.append(command_text)
    return commands


def normalize_optional_fix_reply_severity(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return normalize_severity(value)


def severity_override_note(fix_reply_or_note: dict[str, Any] | str | None) -> str:
    if isinstance(fix_reply_or_note, dict):
        return str(
            fix_reply_or_note.get("severity_note") or fix_reply_or_note.get("severity_override_note") or ""
        ).strip()
    return str(fix_reply_or_note or "").strip()


def fix_reply_explicit_severity(fix_reply: dict[str, Any]) -> tuple[str | None, str | None]:
    if "severity" not in fix_reply or fix_reply.get("severity") in (None, ""):
        return None, None
    severity = normalize_optional_fix_reply_severity(fix_reply.get("severity"))
    if not severity:
        return None, "INVALID_FIX_REPLY_SEVERITY"
    return severity, None


def fix_reply_severity_rejection_reason(fix_reply: dict[str, Any], item: dict[str, Any]) -> str | None:
    explicit_severity, error = fix_reply_explicit_severity(fix_reply)
    if error:
        return error
    if not explicit_severity:
        return None
    first_scene_severity = first_scene_item_severity(item)
    if first_scene_severity and first_scene_severity != explicit_severity and not severity_override_note(fix_reply):
        return "SEVERITY_OVERRIDE_NOTE_REQUIRED"
    return None


def fix_reply_severity_for_publish(fix_reply: dict[str, Any], item: dict[str, Any]) -> tuple[str | None, str | None]:
    explicit_severity, error = fix_reply_explicit_severity(fix_reply)
    if error:
        return None, error
    if explicit_severity:
        conflict = fix_reply_severity_rejection_reason(fix_reply, item)
        if conflict:
            return None, conflict
        return explicit_severity, None
    return first_scene_item_severity(item), None


def return_item_to_claimable_state(item: dict[str, Any]) -> None:
    state, status = returned_claimable_state(item)
    item["state"] = state
    item["status"] = status


def return_expired_items_to_open(session: dict[str, Any], expired: list[Any]) -> None:
    items = session.get("items")
    if not isinstance(items, dict):
        return
    for lease in expired:
        item_id = str(get_field(lease, "item_id"))
        item = items.get(item_id)
        if not isinstance(item, dict):
            continue
        if item.get("active_lease_id") == get_field(lease, "lease_id"):
            return_item_to_claimable_state(item)
            item["claimed_by"] = None
            item["claimed_at"] = None
            item["lease_expires_at"] = None
            item.pop("active_lease_id", None)
