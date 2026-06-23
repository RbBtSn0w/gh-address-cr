from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core import protocol_codes
from gh_address_cr.core.telemetry_attribution import (
    SAFE_STATUSES,
    ExternalTelemetryEvent,
    _append_external_events,
    _load_external_events_with_diagnostics,
    _load_fingerprint_set_with_diagnostics,
    _normalize_external_event,
    _write_fingerprint_set,
)
from gh_address_cr.core.telemetry_safety import (
    _contains_control_character,
    _contains_private_identifier,
    _contains_token_marker,
    _json_loads_strict,
    _looks_like_unnecessary_absolute_path,
    _safe_diagnostic_text,
)


@dataclass
class TelemetryParseResult:
    events: list[ExternalTelemetryEvent]
    rejected_count: int
    unsafe_seen: bool
    malformed_seen: bool
    diagnostics: list[Any]
    events_are_normalized: bool = False

class TelemetryAdapter(ABC):
    @abstractmethod
    def parse(self, raw: str, source: str) -> TelemetryParseResult:
        """Parse raw telemetry into a TelemetryParseResult.

        Expected producer/input failures must be represented by a rejected
        TelemetryParseResult or by raising ValueError/TypeError. Adapter
        implementations should validate payload shape before indexing so
        malformed input does not leak KeyError or IndexError; those exception
        types are treated as adapter bugs and fail loud at the import boundary.
        """
        pass

class TelemetryAdapterRegistry:
    def __init__(self):
        self._adapters: dict[tuple[str, str | None], TelemetryAdapter] = {}

    def register(self, fmt: str, adapter: TelemetryAdapter, source: str | None = None) -> None:
        key = (fmt, source)
        if key in self._adapters:
            raise ValueError(f"Adapter for format '{fmt}' and source '{source}' is already registered.")
        self._adapters[key] = adapter

    def get_adapter(self, fmt: str, source: str | None = None) -> TelemetryAdapter | None:
        if source is not None:
            adapter = self._adapters.get((fmt, source))
            if adapter is not None:
                return adapter
        return self._adapters.get((fmt, None))

    def unregister(self, fmt: str, source: str | None = None) -> None:
        self._adapters.pop((fmt, source), None)

_registry = TelemetryAdapterRegistry()

def register_adapter(fmt: str, adapter: TelemetryAdapter, source: str | None = None) -> None:
    _registry.register(fmt, adapter, source)

def get_adapter(fmt: str, source: str | None = None) -> TelemetryAdapter | None:
    return _registry.get_adapter(fmt, source)

def unregister_adapter(fmt: str, source: str | None = None) -> None:
    _registry.unregister(fmt, source)

class GenericAgentJsonlAdapter(TelemetryAdapter):
    def parse(self, raw: str, source: str) -> TelemetryParseResult:
        accepted: list[ExternalTelemetryEvent] = []
        diagnostics: list[str] = []
        rejected_count = 0
        unsafe_seen = False
        malformed_seen = False

        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = _json_loads_strict(line)
            except json.JSONDecodeError as exc:
                malformed_seen = True
                rejected_count += 1
                diagnostics.append(f"line {line_number}: invalid JSON: {exc.msg}")
                continue
            except ValueError as exc:
                malformed_seen = True
                rejected_count += 1
                diagnostics.append(f"line {line_number}: invalid JSON: {exc}")
                continue
            try:
                event = _normalize_external_event(payload, declared_source=source)
            except ValueError as exc:
                message = str(exc)
                if message.startswith("UNSAFE:"):
                    unsafe_seen = True
                    diagnostics.append(f"line {line_number}: {message.removeprefix('UNSAFE:')}")
                else:
                    malformed_seen = True
                    diagnostics.append(f"line {line_number}: {message}")
                rejected_count += 1
                continue
            accepted.append(event)

        return TelemetryParseResult(
            events=accepted,
            rejected_count=rejected_count,
            unsafe_seen=unsafe_seen,
            malformed_seen=malformed_seen,
            diagnostics=diagnostics,
            events_are_normalized=True,
        )

class CodexHostJsonAdapter(TelemetryAdapter):
    def parse(self, raw: str, source: str) -> TelemetryParseResult:
        try:
            payload = _json_loads_strict(raw)
        except json.JSONDecodeError as exc:
            return TelemetryParseResult([], 1, False, True, [f"invalid JSON: {exc.msg}"])
        except ValueError as exc:
            return TelemetryParseResult([], 1, False, True, [f"invalid JSON: {exc}"])
        if not isinstance(payload, dict):
            return TelemetryParseResult([], 1, False, True, ["codex host payload must be an object"])

        session_id = str(payload.get("session_id") or payload.get("thread_id") or "")
        if not session_id:
            return TelemetryParseResult([], 1, False, True, ["codex host payload missing session_id"])
        turns = payload.get("turns")
        if not isinstance(turns, list):
            return TelemetryParseResult([], 1, False, True, ["codex host payload turns must be a list"])

        events: list[ExternalTelemetryEvent] = []
        diagnostics: list[str] = []
        rejected = 0

        for index, turn in enumerate(turns):
            if not isinstance(turn, dict):
                rejected += 1
                diagnostics.append(f"turn {index}: turn must be an object")
                continue
            event_id = str(turn.get("id") or turn.get("turn_id") or f"turn-{index}")
            duration_ms = _coerce_duration_ms(_first_present(turn, "duration_ms", "duration"))
            if duration_ms is None:
                rejected += 1
                diagnostics.append(f"turn {index}: missing duration_ms")
                continue
            metadata = _codex_turn_metadata(turn)
            events.append(
                ExternalTelemetryEvent(
                    schema_version="telemetry.external.v1",
                    source=source,
                    source_session_id=session_id,
                    event_id=event_id,
                    kind="agent_step",
                    operation=str(turn.get("operation") or "codex.turn"),
                    status=_normalize_host_status(turn.get("status")),
                    duration_ms=duration_ms,
                    started_at=_optional_str(turn.get("started_at")),
                    ended_at=_optional_str(turn.get("ended_at")),
                    metadata=metadata,
                    correlation_id=_optional_str(turn.get("correlation_id")),
                )
            )
            tool_calls = turn.get("tool_calls") or []
            if isinstance(tool_calls, list):
                for tool_index, tool in enumerate(tool_calls):
                    if not isinstance(tool, dict):
                        continue
                    tool_duration = _coerce_duration_ms(_first_present(tool, "duration_ms", "duration")) or 0
                    events.append(
                        ExternalTelemetryEvent(
                            schema_version="telemetry.external.v1",
                            source=source,
                            source_session_id=session_id,
                            event_id=f"{event_id}:tool-{tool_index}",
                            kind="tool_call",
                            operation=str(tool.get("name") or tool.get("operation") or "tool_call"),
                            status=_normalize_host_status(tool.get("status")),
                            duration_ms=tool_duration,
                            started_at=_optional_str(tool.get("started_at")),
                            ended_at=_optional_str(tool.get("ended_at")),
                            metadata={},
                            correlation_id=event_id,
                        )
                    )
        return TelemetryParseResult(events, rejected, False, bool(rejected), diagnostics)

register_adapter("agent-jsonl", GenericAgentJsonlAdapter())
register_adapter("codex-host-json", CodexHostJsonAdapter(), source="codex")

def _normalize_host_status(value: Any) -> str:
    status = str(value or "unknown").lower()
    return status if status in SAFE_STATUSES else "unknown"

def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)

def _coerce_duration_ms(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return int(number)

def _coerce_positive_count(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None

def _first_present(payload: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None

def _codex_turn_metadata(turn: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    tokens = turn.get("tokens")
    if isinstance(tokens, dict):
        for source_key, target_key in (
            ("input", "token_input_count"),
            ("output", "token_output_count"),
            ("total", "token_total_count"),
        ):
            value = _coerce_positive_count(tokens.get(source_key))
            if value is not None:
                metadata[target_key] = value
    tool_calls = turn.get("tool_calls")
    if isinstance(tool_calls, list):
        metadata["tool_call_count"] = len(tool_calls)
    return metadata

def _append_import_summary(paths: core_paths.SessionPaths, summary: dict[str, Any]) -> None:
    path = paths.telemetry_imports_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, sort_keys=True) + "\n")

def _append_import_summary_if_available(paths: core_paths.SessionPaths, summary: dict[str, Any]) -> None:
    try:
        _append_import_summary(paths, summary)
    except OSError:
        return

def _telemetry_write_target_diagnostics(paths: core_paths.SessionPaths) -> list[str]:
    diagnostics: list[str] = []
    targets = (
        ("external telemetry store", paths.external_telemetry_file),
        ("telemetry fingerprint ledger", paths.telemetry_fingerprints_file),
        ("telemetry import ledger", paths.telemetry_imports_file),
    )
    for label, path in targets:
        if path.exists() and not path.is_file():
            diagnostics.append(f"{label} is not a regular file: {path.name}")
        if path.parent.exists() and not path.parent.is_dir():
            diagnostics.append(f"{label} parent is not a directory: {path.parent.name}")
    return diagnostics

def _resolve_import_status(
    *,
    accepted: list,
    rejected_count: int,
    duplicate_count: int,
    unsafe_seen: bool,
    ambiguous_seen: bool,
    malformed_seen: bool,
) -> tuple[str, str, str | None]:
    if ambiguous_seen:
        return "FAILED", "AMBIGUOUS_TELEMETRY_SESSION", None
    if unsafe_seen:
        return "FAILED", "UNSAFE_TELEMETRY_CONTENT", None
    if accepted:
        if rejected_count == 0:
            return "SUCCESS", "TELEMETRY_IMPORTED", None
        return "PARTIAL", "TELEMETRY_PARTIAL", None
    if duplicate_count and not rejected_count:
        return "FAILED", "DUPLICATE_TELEMETRY_IMPORT", "All telemetry events were duplicates."
    if malformed_seen:
        return "FAILED", protocol_codes.MALFORMED_TELEMETRY, None
    return "FAILED", protocol_codes.MALFORMED_TELEMETRY, "No telemetry events were provided."

def _load_import_state(paths, *, source: str, fmt: str):
    existing, storage_diagnostics = _load_external_events_with_diagnostics(paths)
    if storage_diagnostics:
        return None, None, _failed_import_summary(
            paths,
            source=source,
            fmt=fmt,
            reason_code="CORRUPTED_TELEMETRY_STORE",
            diagnostics=storage_diagnostics,
        )

    write_diagnostics = _telemetry_write_target_diagnostics(paths)
    if write_diagnostics:
        return None, None, _failed_import_summary(
            paths,
            source=source,
            fmt=fmt,
            reason_code="CORRUPTED_TELEMETRY_STORE",
            diagnostics=write_diagnostics,
            append_if_available=True,
        )
    existing_fingerprints, fingerprint_diagnostics = _load_fingerprint_set_with_diagnostics(paths)
    if fingerprint_diagnostics:
        return None, None, _failed_import_summary(
            paths,
            source=source,
            fmt=fmt,
            reason_code="CORRUPTED_TELEMETRY_STORE",
            diagnostics=fingerprint_diagnostics,
            append_if_available=True,
        )
    existing_fingerprints.update(event.identity for event in existing)
    return existing, existing_fingerprints, None

@dataclass
class _ProcessedEventsResult:
    accepted: list[ExternalTelemetryEvent]
    accepted_fingerprints: list[str]
    duplicate_fingerprints: list[str]
    observed_sessions: set[str]
    duplicate_count: int
    unsafe_seen: bool
    malformed_seen: bool
    rejected_count: int

def _process_imported_events(
    accepted_events: list[ExternalTelemetryEvent],
    trusted_normalized_events: bool,
    source: str,
    existing_fingerprints: set[str],
    diagnostics: list[str],
    unsafe_seen: bool,
    malformed_seen: bool,
    rejected_count: int,
) -> _ProcessedEventsResult:
    accepted: list[ExternalTelemetryEvent] = []
    accepted_fingerprints: list[str] = []
    duplicate_fingerprints: list[str] = []
    observed_sessions: set[str] = set()
    duplicate_count = 0

    for idx, event in enumerate(accepted_events):
        if not isinstance(event, ExternalTelemetryEvent):
            raise TypeError(
                f"Event must be an ExternalTelemetryEvent instance, got {type(event).__name__}"
            )
        try:
            normalized_event = event
            if not trusted_normalized_events:
                normalized_event = _normalize_external_event(event.to_dict(), declared_source=source)
        except ValueError as exc:
            message = str(exc)
            if message.startswith("UNSAFE:"):
                unsafe_seen = True
                diagnostics.append(
                    f"event index {idx}: {_safe_diagnostic_text(message.removeprefix('UNSAFE:'))}"
                )
            else:
                malformed_seen = True
                diagnostics.append(f"event index {idx}: {_safe_diagnostic_text(message)}")
            rejected_count += 1
            continue

        observed_sessions.add(normalized_event.source_session_id)
        if normalized_event.identity in existing_fingerprints:
            duplicate_count += 1
            duplicate_fingerprints.append(normalized_event.identity)
            continue
        existing_fingerprints.add(normalized_event.identity)
        accepted_fingerprints.append(normalized_event.identity)
        accepted.append(normalized_event)

    return _ProcessedEventsResult(
        accepted=accepted,
        accepted_fingerprints=accepted_fingerprints,
        duplicate_fingerprints=duplicate_fingerprints,
        observed_sessions=observed_sessions,
        duplicate_count=duplicate_count,
        unsafe_seen=unsafe_seen,
        malformed_seen=malformed_seen,
        rejected_count=rejected_count,
    )

def import_external_telemetry(
    repo: str, pr_number: str, *, source: str, fmt: str, raw: str
) -> dict[str, Any]:
    paths = core_paths.SessionPaths(repo, pr_number)
    adapter = get_adapter(fmt, source=source)
    if adapter is None:
        reported_format = _reported_format_label(fmt)
        return _failed_import_summary(
            paths,
            source=source,
            fmt=fmt,
            reason_code="UNSUPPORTED_TELEMETRY_FORMAT",
            diagnostics=[f"Unsupported telemetry format: {reported_format}"],
        )

    existing, existing_fingerprints, load_failure = _load_import_state(paths, source=source, fmt=fmt)
    if load_failure is not None:
        return load_failure

    try:
        parse_result = adapter.parse(raw, source)
        if not isinstance(parse_result, TelemetryParseResult):
            raise TypeError(
                f"Adapter parse must return a TelemetryParseResult instance, got {type(parse_result).__name__}"
            )
    except (TypeError, ValueError) as exc:
        return _failed_import_summary(
            paths,
            source=source,
            fmt=fmt,
            reason_code=protocol_codes.MALFORMED_TELEMETRY,
            diagnostics=[f"Adapter parsing failed: {type(exc).__name__}"],
        )

    accepted_events = parse_result.events
    rejected_count = parse_result.rejected_count
    unsafe_seen = parse_result.unsafe_seen
    malformed_seen = parse_result.malformed_seen

    try:
        if not isinstance(parse_result.diagnostics, list):
            raise TypeError(
                f"Adapter diagnostics must be a list, got {type(parse_result.diagnostics).__name__}"
            )
        diagnostics: list[str] = []
        for diag in parse_result.diagnostics:
            diagnostics.append(_safe_diagnostic_text(str(diag)))
    except (TypeError, ValueError) as exc:
        return _failed_import_summary(
            paths,
            source=source,
            fmt=fmt,
            reason_code=protocol_codes.MALFORMED_TELEMETRY,
            diagnostics=[f"Adapter diagnostics processing failed: {type(exc).__name__}"],
        )

    trusted_normalized_events = (
        parse_result.events_are_normalized and type(adapter) is GenericAgentJsonlAdapter
    )

    try:
        proc_result = _process_imported_events(
            accepted_events,
            trusted_normalized_events,
            source,
            existing_fingerprints,
            diagnostics,
            unsafe_seen,
            malformed_seen,
            rejected_count,
        )
        accepted = proc_result.accepted
        accepted_fingerprints = proc_result.accepted_fingerprints
        duplicate_fingerprints = proc_result.duplicate_fingerprints
        observed_sessions = proc_result.observed_sessions
        duplicate_count = proc_result.duplicate_count
        unsafe_seen = proc_result.unsafe_seen
        malformed_seen = proc_result.malformed_seen
        rejected_count = proc_result.rejected_count
    except (TypeError, ValueError) as exc:
        return _failed_import_summary(
            paths,
            source=source,
            fmt=fmt,
            reason_code=protocol_codes.MALFORMED_TELEMETRY,
            diagnostics=[f"Adapter event processing failed: {type(exc).__name__}"],
        )

    ambiguous_seen = len(observed_sessions) > 1
    if unsafe_seen:
        rejected_count += len(accepted)
        accepted = []
        accepted_fingerprints = []
    if ambiguous_seen:
        diagnostics.append(
            "ambiguous telemetry session: multiple source_session_id values in one import"
        )
        rejected_count += len(accepted)
        accepted = []
        accepted_fingerprints = []

    status, reason_code, extra_diagnostic = _resolve_import_status(
        accepted=accepted,
        rejected_count=rejected_count,
        duplicate_count=duplicate_count,
        unsafe_seen=unsafe_seen,
        ambiguous_seen=ambiguous_seen,
        malformed_seen=malformed_seen,
    )
    if extra_diagnostic is not None:
        diagnostics.append(extra_diagnostic)

    if accepted and status in {"SUCCESS", "PARTIAL"}:
        _write_fingerprint_set(paths, existing_fingerprints)
        _append_external_events(paths, accepted)

    summary = _import_summary(
        paths,
        source=source,
        fmt=fmt,
        status=status,
        reason_code=reason_code,
        accepted_count=len(accepted),
        rejected_count=rejected_count,
        duplicate_count=duplicate_count,
        accepted_fingerprints=accepted_fingerprints,
        duplicate_fingerprints=duplicate_fingerprints,
        diagnostics=diagnostics,
    )
    _append_import_summary(paths, summary)
    return summary

def input_unavailable_import_summary(
    repo: str, pr_number: str, *, source: str, fmt: str
) -> dict[str, Any]:
    paths = core_paths.SessionPaths(repo, pr_number)
    summary = _import_summary(
        paths,
        source=source,
        fmt=fmt,
        status="FAILED",
        reason_code="TELEMETRY_INPUT_UNAVAILABLE",
        accepted_count=0,
        rejected_count=0,
        duplicate_count=0,
        accepted_fingerprints=[],
        duplicate_fingerprints=[],
        diagnostics=["telemetry input unavailable"],
    )
    _append_import_summary(paths, summary)
    return summary

def hook_unavailable_import_summary(
    repo: str, pr_number: str, *, source: str, fmt: str
) -> dict[str, Any]:
    paths = core_paths.SessionPaths(repo, pr_number)
    summary = _import_summary(
        paths,
        source=source,
        fmt=fmt,
        status="FAILED",
        reason_code="TELEMETRY_HOOK_UNAVAILABLE",
        accepted_count=0,
        rejected_count=0,
        duplicate_count=0,
        accepted_fingerprints=[],
        duplicate_fingerprints=[],
        diagnostics=["host telemetry hook import unavailable"],
    )
    _append_import_summary(paths, summary)
    return summary

def autodiscovery_miss_import_summary(
    repo: str, pr_number: str, *, diagnostics: list[str]
) -> dict[str, Any]:
    paths = core_paths.SessionPaths(repo, pr_number)
    summary = _import_summary(
        paths,
        source="host-autodiscovery",
        fmt="agent-jsonl",
        status="FAILED",
        reason_code="TELEMETRY_AUTODISCOVERY_MISS",
        accepted_count=0,
        rejected_count=0,
        duplicate_count=0,
        accepted_fingerprints=[],
        duplicate_fingerprints=[],
        diagnostics=[_safe_diagnostic_text(diagnostic) for diagnostic in diagnostics],
    )
    _append_import_summary_if_available(paths, summary)
    return summary

def _import_summary(
    paths: core_paths.SessionPaths,
    *,
    source: str,
    fmt: str,
    status: str,
    reason_code: str,
    accepted_count: int,
    rejected_count: int,
    duplicate_count: int,
    accepted_fingerprints: list[str],
    duplicate_fingerprints: list[str],
    diagnostics: list[str],
) -> dict[str, Any]:
    from datetime import datetime, timezone

    return {
        "status": status,
        "reason_code": reason_code,
        "repo": paths.repo,
        "pr_number": paths.pr_number,
        "source": _reported_source_label(source),
        "format": _reported_format_label(fmt),
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "duplicate_count": duplicate_count,
        "accepted_fingerprints": accepted_fingerprints,
        "duplicate_fingerprints": duplicate_fingerprints,
        "diagnostics": diagnostics,
        "next_action": "RUN_TELEMETRY_SUMMARY"
        if status in {"SUCCESS", "PARTIAL"}
        else "FIX_TELEMETRY_INPUT",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }

def _reported_source_label(source: str) -> str:
    if _contains_control_character(source):
        return "[redacted]"
    if _contains_token_marker(source):
        return "[redacted]"
    if _contains_private_identifier(source):
        return "[redacted]"
    if _looks_like_unnecessary_absolute_path(source):
        return "[redacted]"
    return source

def _reported_format_label(fmt: str) -> str:
    if _contains_control_character(fmt):
        return "[redacted]"
    return _reported_source_label(fmt)

def _failed_import_summary(
    paths: core_paths.SessionPaths,
    *,
    source: str,
    fmt: str,
    reason_code: str,
    diagnostics: list[str],
    append_if_available: bool = False,
) -> dict[str, Any]:
    summary = _import_summary(
        paths,
        source=source,
        fmt=fmt,
        status="FAILED",
        reason_code=reason_code,
        accepted_count=0,
        rejected_count=0,
        duplicate_count=0,
        accepted_fingerprints=[],
        duplicate_fingerprints=[],
        diagnostics=diagnostics,
    )
    if append_if_available:
        _append_import_summary_if_available(paths, summary)
    else:
        _append_import_summary(paths, summary)
    return summary
