from __future__ import annotations

import json
import uuid
from datetime import datetime
from hashlib import sha256
from typing import Any, cast

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.telemetry_models import SAFE_KINDS, SAFE_STATUSES, ExternalTelemetryEvent
from gh_address_cr.core.telemetry_safety import (
    _json_loads_strict,
    _safe_correlation_id,
    _safe_diagnostic_text,
    _safe_identity_label,
    _safe_metadata,
    _safe_operation,
    _safe_optional_timestamp,
    _safe_source_label,
    _safe_source_session_id,
)


def normalize_external_event(payload: object, *, declared_source: str) -> ExternalTelemetryEvent:
    if not isinstance(payload, dict):
        raise ValueError("record must be a JSON object")
    source_text = str(payload.get("source") or declared_source)
    required = ("kind", "operation", "status")
    missing = [key for key in required if not payload.get(key)]
    if not source_text:
        missing.insert(0, "source")
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
    source = _safe_source_label(source_text)
    payload_dict = cast(dict[str, Any], payload)
    schema_version = _safe_identity_label(str(payload_dict.get("schema_version") or "1.0"), field="schema_version")
    kind = _safe_identity_label(str(payload_dict["kind"]), field="kind")
    status = _safe_identity_label(str(payload_dict["status"]), field="status")
    if kind not in SAFE_KINDS:
        raise ValueError(f"unsupported kind: {kind}")
    if status not in SAFE_STATUSES:
        raise ValueError(f"unsupported status: {status}")
    duration_ms = event_duration_ms(payload_dict)
    metadata = _safe_metadata(payload_dict.get("metadata") or {})
    raw_session_id = payload_dict.get("source_session_id")
    session_id = _safe_source_session_id(
        raw_session_id if isinstance(raw_session_id, str) and raw_session_id else "unknown-session"
    )
    operation_payload = payload_dict["operation"]
    if not isinstance(operation_payload, str):
        raise ValueError("operation must be a string")
    operation = _safe_operation(operation_payload)
    started_at = _safe_optional_timestamp(payload_dict.get("started_at"), field="started_at")
    ended_at = _safe_optional_timestamp(payload_dict.get("ended_at"), field="ended_at")
    correlation_id = (
        _safe_correlation_id(str(payload_dict["correlation_id"])) if payload_dict.get("correlation_id") else None
    )
    event_id = str(
        (
            _safe_identity_label(str(payload_dict["event_id"]), field="event_id")
            if payload_dict.get("event_id")
            else None
        )
        or derive_event_id(
            source=source,
            source_session_id=session_id,
            kind=kind,
            operation=operation,
            status=status,
            duration_ms=duration_ms,
            started_at=started_at,
            ended_at=ended_at,
            correlation_id=correlation_id,
        )
    )
    event = ExternalTelemetryEvent(
        schema_version=schema_version,
        source=source,
        source_session_id=session_id,
        event_id=event_id,
        kind=kind,
        operation=operation,
        status=status,
        duration_ms=duration_ms,
        started_at=started_at,
        ended_at=ended_at,
        metadata=metadata,
        correlation_id=correlation_id,
    )
    return ExternalTelemetryEvent(**{**event.to_dict(), "event_fingerprint": event_fingerprint(event)})


def derive_event_id(
    *,
    source: str,
    source_session_id: str,
    kind: str,
    operation: str,
    status: str,
    duration_ms: int,
    started_at: str | None,
    ended_at: str | None,
    correlation_id: str | None,
) -> str:
    canonical = {
        "source": source,
        "source_session_id": source_session_id,
        "kind": kind,
        "operation": operation,
        "status": status,
        "duration_ms": duration_ms,
        "started_at": started_at,
        "ended_at": ended_at,
        "correlation_id": correlation_id,
    }
    return uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(canonical, sort_keys=True, separators=(",", ":"))).hex


def event_fingerprint(event: ExternalTelemetryEvent) -> str:
    if event.correlation_id and event.started_at and event.ended_at:
        event_identity = event.correlation_id
    elif event.correlation_id:
        event_identity = f"{event.correlation_id}:{event.event_id}"
    else:
        event_identity = event.event_id
    canonical = {
        "source": event.source,
        "source_session_id": event.source_session_id,
        "event_identity": event_identity,
        "kind": event.kind,
        "operation": event.operation,
        "duration_ms": event.duration_ms,
        "started_at": event.started_at,
        "ended_at": event.ended_at,
        "status": event.status,
        "correlation_id": event.correlation_id,
    }
    return sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def event_duration_ms(payload: dict[str, Any]) -> int:
    if payload.get("duration_ms") is not None:
        value = payload["duration_ms"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("duration_ms must be an integer") from None
        if value < 0:
            raise ValueError("duration_ms must be non-negative")
        return value
    started = payload.get("started_at")
    ended = payload.get("ended_at")
    if not started or not ended:
        raise ValueError("duration_ms or started_at plus ended_at is required")
    try:
        start_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("started_at and ended_at must be ISO timestamps") from None
    if (start_dt.tzinfo is None) != (end_dt.tzinfo is None):
        raise ValueError("timestamp timezone awareness must match")
    try:
        duration = int((end_dt - start_dt).total_seconds() * 1000)
    except TypeError:
        raise ValueError("timestamp timezone awareness must match") from None
    if duration < 0:
        raise ValueError("event duration must be non-negative")
    return duration


def load_external_events(paths: core_paths.SessionPaths) -> list[ExternalTelemetryEvent]:
    events, _diagnostics = load_external_events_with_diagnostics(paths)
    return events


def load_external_events_with_diagnostics(
    paths: core_paths.SessionPaths,
) -> tuple[list[ExternalTelemetryEvent], list[str]]:
    path = paths.external_telemetry_file
    if not path.exists():
        return [], []
    if not path.is_file():
        return [], [f"external telemetry store is not a regular file: {path.name}"]
    events: list[ExternalTelemetryEvent] = []
    diagnostics: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = _json_loads_strict(line)
                    events.append(load_stored_external_event(payload))
                except json.JSONDecodeError as exc:
                    diagnostics.append(f"external telemetry line {line_number}: invalid JSON: {exc.msg}")
                except ValueError as exc:
                    diagnostics.append(f"external telemetry line {line_number}: {_safe_diagnostic_text(str(exc))}")
    except OSError as exc:
        return [], [f"external telemetry unreadable: {exc}"]
    return events, diagnostics


def sanitize_stored_identity_field(field: str, value: str) -> str:
    if field == "kind":
        kind = _safe_identity_label(value, field=field)
        if kind not in SAFE_KINDS:
            raise ValueError(f"unsupported kind: {kind}")
        return kind
    if field == "status":
        status = _safe_identity_label(value, field=field)
        if status not in SAFE_STATUSES:
            raise ValueError(f"unsupported status: {status}")
        return status
    if field in ("schema_version", "event_id"):
        return _safe_identity_label(value, field=field)
    if field == "source_session_id":
        return _safe_source_session_id(value)
    if field == "operation":
        return _safe_operation(value)
    return value


def extract_stored_required_strings(payload: dict[str, Any], source: str) -> dict[str, str]:
    required_strings = ("schema_version", "source_session_id", "event_id", "kind", "operation", "status")
    values: dict[str, str] = {"source": _safe_source_label(source)}
    missing: list[str] = []
    for field in required_strings:
        value = payload.get(field)
        if value in (None, ""):
            missing.append(field)
            continue
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        values[field] = sanitize_stored_identity_field(field, value)
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
    return values


def load_stored_external_event(payload: object) -> ExternalTelemetryEvent:
    if not isinstance(payload, dict):
        raise ValueError("record must be a JSON object")
    payload_dict = cast(dict[str, Any], payload)
    source = payload_dict.get("source")
    if not source:
        raise ValueError("missing required field(s): source")
    if not isinstance(source, str):
        raise ValueError("source must be a string")
    values = extract_stored_required_strings(payload_dict, source)
    duration_ms = payload_dict.get("duration_ms")
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
        raise ValueError("duration_ms must be an integer")
    if duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    metadata = payload_dict.get("metadata")
    if metadata is None:
        metadata = {}
    metadata = _safe_metadata(metadata)
    started_at = stored_optional_timestamp(payload_dict.get("started_at"), field="started_at")
    ended_at = stored_optional_timestamp(payload_dict.get("ended_at"), field="ended_at")
    correlation_raw = payload_dict.get("correlation_id")
    correlation_id = None
    if correlation_raw is not None:
        if not isinstance(correlation_raw, str):
            raise ValueError("correlation_id must be a string")
        correlation_id = _safe_correlation_id(correlation_raw)
    stored_fingerprint = payload_dict.get("event_fingerprint")
    if stored_fingerprint is not None and not isinstance(stored_fingerprint, str):
        raise ValueError("event_fingerprint must be a string")
    event = ExternalTelemetryEvent(
        schema_version=values["schema_version"],
        source=values["source"],
        source_session_id=values["source_session_id"],
        event_id=values["event_id"],
        kind=values["kind"],
        operation=values["operation"],
        status=values["status"],
        duration_ms=duration_ms,
        started_at=started_at,
        ended_at=ended_at,
        metadata=dict(metadata),
        correlation_id=correlation_id,
        event_fingerprint=stored_fingerprint or "",
    )
    canonical_fingerprint = event_fingerprint(event)
    if event.event_fingerprint != canonical_fingerprint:
        event = ExternalTelemetryEvent(**{**event.to_dict(), "event_fingerprint": canonical_fingerprint})
    return event


def stored_optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def stored_optional_timestamp(value: object, *, field: str) -> str | None:
    value_str = stored_optional_string(value, field=field)
    if value_str is None:
        return None
    return _safe_optional_timestamp(value_str, field=field)
