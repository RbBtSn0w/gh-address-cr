from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.io import write_json_atomic
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

SAFE_STATUSES = {"success", "failure", "timeout", "cancelled", "unknown"}
SAFE_KINDS = {"tool_call", "command", "wait", "retry", "validation", "agent_step"}


@dataclass(frozen=True)
class ExternalTelemetryEvent:
    schema_version: str
    source: str
    source_session_id: str
    event_id: str
    kind: str
    operation: str
    status: str
    duration_ms: int
    started_at: str | None = None
    ended_at: str | None = None
    metadata: dict[str, Any] | None = None
    correlation_id: str | None = None
    event_fingerprint: str = ""

    @property
    def identity(self) -> str:
        return self.event_fingerprint or f"{self.source}:{self.source_session_id}:{self.event_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "source_session_id": self.source_session_id,
            "event_id": self.event_id,
            "kind": self.kind,
            "operation": self.operation,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "metadata": dict(self.metadata or {}),
            "correlation_id": self.correlation_id,
            "event_fingerprint": self.event_fingerprint,
        }


def _normalize_external_event(payload: object, *, declared_source: str) -> ExternalTelemetryEvent:
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
    schema_version = _safe_identity_label(str(payload.get("schema_version") or "1.0"), field="schema_version")
    kind = _safe_identity_label(str(payload["kind"]), field="kind")
    status = _safe_identity_label(str(payload["status"]), field="status")
    if kind not in SAFE_KINDS:
        raise ValueError(f"unsupported kind: {kind}")
    if status not in SAFE_STATUSES:
        raise ValueError(f"unsupported status: {status}")
    duration_ms = _event_duration_ms(payload)
    metadata = _safe_metadata(payload.get("metadata") or {})
    session_id = _safe_source_session_id(str(payload.get("source_session_id") or "unknown-session"))
    operation_payload = payload["operation"]
    if not isinstance(operation_payload, str):
        raise ValueError("operation must be a string")
    operation = _safe_operation(operation_payload)
    started_at = _safe_optional_timestamp(payload.get("started_at"), field="started_at")
    ended_at = _safe_optional_timestamp(payload.get("ended_at"), field="ended_at")
    correlation_id = _safe_correlation_id(str(payload["correlation_id"])) if payload.get("correlation_id") else None
    event_id = str(
        (_safe_identity_label(str(payload["event_id"]), field="event_id") if payload.get("event_id") else None)
        or _derive_event_id(
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
    return ExternalTelemetryEvent(**{**event.to_dict(), "event_fingerprint": _event_fingerprint(event)})


def _derive_event_id(
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


def _event_fingerprint(event: ExternalTelemetryEvent) -> str:
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


def _event_duration_ms(payload: dict[str, Any]) -> int:
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


def _load_external_events(paths: core_paths.SessionPaths) -> list[ExternalTelemetryEvent]:
    events, _diagnostics = _load_external_events_with_diagnostics(paths)
    return events


def _load_external_events_with_diagnostics(paths: core_paths.SessionPaths) -> tuple[list[ExternalTelemetryEvent], list[str]]:
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
                    events.append(_load_stored_external_event(payload))
                except json.JSONDecodeError as exc:
                    diagnostics.append(f"external telemetry line {line_number}: invalid JSON: {exc.msg}")
                except ValueError as exc:
                    diagnostics.append(f"external telemetry line {line_number}: {_safe_diagnostic_text(str(exc))}")
    except OSError as exc:
        return [], [f"external telemetry unreadable: {exc}"]
    return events, diagnostics


def _sanitize_stored_identity_field(field: str, value: str) -> str:
    """Apply the field-specific sanitization/whitelist for a stored telemetry string field."""
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


def _extract_stored_required_strings(payload: dict, source: str) -> dict[str, str]:
    """Validate and sanitize the required string fields of a stored telemetry record."""
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
        values[field] = _sanitize_stored_identity_field(field, value)
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
    return values


def _load_stored_external_event(payload: object) -> ExternalTelemetryEvent:
    if not isinstance(payload, dict):
        raise ValueError("record must be a JSON object")
    source = payload.get("source")
    if not source:
        raise ValueError("missing required field(s): source")
    if not isinstance(source, str):
        raise ValueError("source must be a string")
    values = _extract_stored_required_strings(payload, source)
    duration_ms = payload.get("duration_ms")
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
        raise ValueError("duration_ms must be an integer")
    if duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    metadata = payload.get("metadata")
    if metadata is None:
        metadata = {}
    metadata = _safe_metadata(metadata)
    started_at = _stored_optional_timestamp(payload.get("started_at"), field="started_at")
    ended_at = _stored_optional_timestamp(payload.get("ended_at"), field="ended_at")
    correlation_raw = payload.get("correlation_id")
    correlation_id = None
    if correlation_raw is not None:
        if not isinstance(correlation_raw, str):
            raise ValueError("correlation_id must be a string")
        correlation_id = _safe_correlation_id(correlation_raw)
    event_fingerprint = payload.get("event_fingerprint")
    if event_fingerprint is not None and not isinstance(event_fingerprint, str):
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
        event_fingerprint=event_fingerprint or "",
    )
    canonical_fingerprint = _event_fingerprint(event)
    if event.event_fingerprint != canonical_fingerprint:
        event = ExternalTelemetryEvent(**{**event.to_dict(), "event_fingerprint": canonical_fingerprint})
    return event


def _stored_optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _stored_optional_timestamp(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return _safe_optional_timestamp(value, field=field)


def _dedupe_events(events: list[ExternalTelemetryEvent]) -> tuple[list[ExternalTelemetryEvent], list[str]]:
    seen: set[str] = set()
    deduped: list[ExternalTelemetryEvent] = []
    diagnostics: list[str] = []
    for event in events:
        fingerprint = event.identity
        if fingerprint in seen:
            diagnostics.append(f"duplicate event fingerprint ignored: {fingerprint}")
            continue
        seen.add(fingerprint)
        deduped.append(event)
    return deduped, diagnostics


def _dedupe_correlated_events(events: list[ExternalTelemetryEvent]) -> tuple[list[ExternalTelemetryEvent], list[str]]:
    seen: dict[str, ExternalTelemetryEvent] = {}
    deduped: list[ExternalTelemetryEvent] = []
    diagnostics: list[str] = []
    for event in events:
        key = _correlation_dedupe_key(event)
        if key and key in seen and _is_runtime_external_overlap(seen[key], event):
            diagnostics.append(f"correlated telemetry event ignored: {event.source}:{event.event_id}")
            continue
        if key:
            seen[key] = event
        deduped.append(event)
    return deduped, diagnostics


def _is_runtime_external_overlap(first: ExternalTelemetryEvent, second: ExternalTelemetryEvent) -> bool:
    return first.source != second.source and "runtime" in {first.source, second.source}


def _correlation_dedupe_key(event: ExternalTelemetryEvent) -> str | None:
    correlation = event.correlation_id or (event.event_id if event.source == "runtime" else None)
    if not correlation:
        return None
    return f"{correlation}:{event.operation}:{event.status}"


def _load_fingerprint_set(paths: core_paths.SessionPaths) -> set[str]:
    fingerprints, _diagnostics = _load_fingerprint_set_with_diagnostics(paths)
    return fingerprints


def _load_fingerprint_set_with_diagnostics(paths: core_paths.SessionPaths) -> tuple[set[str], list[str]]:
    path = paths.telemetry_fingerprints_file
    if not path.exists():
        return set(), []
    if not path.is_file():
        return set(), [f"telemetry fingerprint ledger is not a regular file: {path.name}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return set(), [f"telemetry fingerprint ledger unreadable: {exc}"]
    except json.JSONDecodeError as exc:
        return set(), [f"telemetry fingerprint ledger invalid JSON: {exc.msg}"]
    if not isinstance(payload, dict):
        return set(), ["telemetry fingerprint ledger record must be a JSON object"]
    fingerprints = payload.get("event_fingerprints")
    if not isinstance(fingerprints, list):
        return set(), ["telemetry fingerprint ledger event_fingerprints must be a list"]
    return {str(value) for value in fingerprints if value}, []


def _write_fingerprint_set(paths: core_paths.SessionPaths, fingerprints: set[str]) -> None:
    path = paths.telemetry_fingerprints_file
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"event_fingerprints": sorted(fingerprints)}
    write_json_atomic(path, payload)


def _append_external_events(paths: core_paths.SessionPaths, events: list[ExternalTelemetryEvent]) -> None:
    path = paths.external_telemetry_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
