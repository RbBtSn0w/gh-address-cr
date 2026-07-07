from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core import protocol_codes
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.telemetry_adapters import (
    CodexHostJsonAdapter,
    GenericAgentJsonlAdapter,
    TelemetryAdapter,
    get_adapter,
    register_adapter,
    unregister_adapter,
)
from gh_address_cr.core.telemetry_external_events import (
    event_fingerprint as _event_fingerprint,
)
from gh_address_cr.core.telemetry_external_events import (
    load_external_events_with_diagnostics as _load_external_events_with_diagnostics,
)
from gh_address_cr.core.telemetry_external_events import (
    normalize_external_event as _normalize_external_event,
)
from gh_address_cr.core.telemetry_models import (
    EfficiencyReportPayload,
    ExternalTelemetryEvent,
    TelemetryParseResult,
)
from gh_address_cr.core.telemetry_reporting import (
    _aggregate_host_metrics,
    _cli_health_issues,
    _confidence_for_coverage,
    _coverage_label,
    _error_prone_operations,
    _inefficiency_flags,
    _safe_os_error_diagnostic,
    _source_rows,
)
from gh_address_cr.core.telemetry_runtime import (
    SessionTelemetry,
    _log_telemetry_failure,
    configure_context_safely,
)
from gh_address_cr.core.telemetry_safety import (
    _contains_control_character,
    _contains_private_identifier,
    _contains_token_marker,
    _looks_like_unnecessary_absolute_path,
    _safe_diagnostic_text,
    _safe_runtime_operation,
)

__all__ = [
    "CodexHostJsonAdapter",
    "ExternalTelemetryEvent",
    "GenericAgentJsonlAdapter",
    "SessionTelemetry",
    "TelemetryAdapter",
    "TelemetryParseResult",
    "autodiscovery_miss_import_summary",
    "build_efficiency_report",
    "configure_context_safely",
    "get_adapter",
    "hook_unavailable_import_summary",
    "import_external_telemetry",
    "input_unavailable_import_summary",
    "_log_telemetry_failure",
    "register_adapter",
    "unregister_adapter",
]

register_adapter(
    "agent-jsonl",
    GenericAgentJsonlAdapter(
        normalize_external_event=lambda payload, source: _normalize_external_event(payload, declared_source=source)
    ),
)
register_adapter("codex-host-json", CodexHostJsonAdapter(), source="codex")


def _failed_import_summary(
    paths: core_paths.SessionPaths,
    *,
    source: str,
    fmt: str,
    reason_code: str,
    diagnostics: list[str],
    append_if_available: bool = False,
) -> dict[str, Any]:
    """Build a zero-count FAILED import summary, persist it, and return it."""
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


def _resolve_import_status(
    *,
    accepted: list[ExternalTelemetryEvent],
    rejected_count: int,
    duplicate_count: int,
    unsafe_seen: bool,
    ambiguous_seen: bool,
    malformed_seen: bool,
) -> tuple[str, str, str | None]:
    """Map the tallied import outcome to (status, reason_code, optional extra diagnostic)."""
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


def _load_import_state(
    paths: core_paths.SessionPaths, *, source: str, fmt: str
) -> tuple[list[ExternalTelemetryEvent], set[str], None] | tuple[None, None, dict[str, Any]]:
    """Load existing events + fingerprints, returning a failure summary if storage is corrupt.

    Returns ``(existing, existing_fingerprints, None)`` on success, or
    ``(None, None, failure_summary)`` when any precondition fails.
    """
    existing, storage_diagnostics = _load_external_events_with_diagnostics(paths)
    if storage_diagnostics:
        return (
            None,
            None,
            _failed_import_summary(
                paths, source=source, fmt=fmt, reason_code="CORRUPTED_TELEMETRY_STORE", diagnostics=storage_diagnostics
            ),
        )
    write_diagnostics = _telemetry_write_target_diagnostics(paths)
    if write_diagnostics:
        return (
            None,
            None,
            _failed_import_summary(
                paths,
                source=source,
                fmt=fmt,
                reason_code="CORRUPTED_TELEMETRY_STORE",
                diagnostics=write_diagnostics,
                append_if_available=True,
            ),
        )
    existing_fingerprints, fingerprint_diagnostics = _load_fingerprint_set_with_diagnostics(paths)
    if fingerprint_diagnostics:
        return (
            None,
            None,
            _failed_import_summary(
                paths,
                source=source,
                fmt=fmt,
                reason_code="CORRUPTED_TELEMETRY_STORE",
                diagnostics=fingerprint_diagnostics,
                append_if_available=True,
            ),
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
            raise TypeError(f"Event must be an ExternalTelemetryEvent instance, got {type(event).__name__}")
        try:
            normalized_event = event
            if not trusted_normalized_events:
                normalized_event = _normalize_external_event(event.to_dict(), declared_source=source)
        except ValueError as exc:
            message = str(exc)
            if message.startswith("UNSAFE:"):
                unsafe_seen = True
                diagnostics.append(f"event index {idx}: {_safe_diagnostic_text(message.removeprefix('UNSAFE:'))}")
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


def import_external_telemetry(repo: str, pr_number: str, *, source: str, fmt: str, raw: str) -> dict[str, Any]:
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
    if load_failure is not None or existing_fingerprints is None:
        return load_failure or {}

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
            raise TypeError(f"Adapter diagnostics must be a list, got {type(parse_result.diagnostics).__name__}")
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

    trusted_normalized_events = parse_result.events_are_normalized and type(adapter) is GenericAgentJsonlAdapter

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
        diagnostics.append("ambiguous telemetry session: multiple source_session_id values in one import")
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


def input_unavailable_import_summary(repo: str, pr_number: str, *, source: str, fmt: str) -> dict[str, Any]:
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


def hook_unavailable_import_summary(repo: str, pr_number: str, *, source: str, fmt: str) -> dict[str, Any]:
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


def autodiscovery_miss_import_summary(repo: str, pr_number: str, *, diagnostics: list[str]) -> dict[str, Any]:
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


TELEMETRY_OVERHEAD_BUDGET_MS = 250


def build_efficiency_report(repo: str, pr_number: str) -> EfficiencyReportPayload:
    overhead_started_at = time.perf_counter()
    paths = core_paths.SessionPaths(repo, pr_number)
    runtime_events = _runtime_events(paths)
    external_events, diagnostics = _load_external_events_with_diagnostics(paths)
    storage_diagnostics = list(diagnostics)
    if storage_diagnostics:
        external_events = []
    import_diagnostics = _load_import_diagnostics(paths)
    diagnostics.extend(import_diagnostics)
    runtime_events, runtime_dedupe_diagnostics = _dedupe_events(runtime_events)
    external_events, external_dedupe_diagnostics = _dedupe_events(external_events)
    diagnostics.extend(runtime_dedupe_diagnostics)
    diagnostics.extend(external_dedupe_diagnostics)
    events = [*runtime_events, *external_events]
    events, dedupe_diagnostics = _dedupe_events(events)
    diagnostics.extend(dedupe_diagnostics)
    events, correlation_dedupe_diagnostics = _dedupe_correlated_events(events)
    diagnostics.extend(correlation_dedupe_diagnostics)
    sources = _source_rows(runtime_events, external_events)
    coverage_diagnostics = list(storage_diagnostics)
    if _has_unrecovered_import_diagnostics(paths):
        coverage_diagnostics.extend(import_diagnostics)
    coverage_label = _coverage_label(runtime_events, external_events, coverage_diagnostics)
    total_events = len(events)
    known_status_events = [event for event in events if event.status != "unknown"]
    success_count = sum(1 for event in known_status_events if event.status == "success")
    success_rate = (success_count / len(known_status_events)) * 100.0 if known_status_events else 0.0
    total_duration = sum(event.duration_ms for event in events)
    # Inline generator expression incurs overhead; explicitly loop and fast return.
    duration_observed = False
    for event in events:
        if event.duration_ms > 0:
            duration_observed = True
            break
    host_metrics = _aggregate_host_metrics(external_events)
    timed_events = [event for event in events if event.duration_ms > 0]
    slowest = sorted(timed_events, key=lambda event: event.duration_ms, reverse=True)[:3]
    if events and not duration_observed and "TELEMETRY_TIMING_UNAVAILABLE" not in diagnostics:
        diagnostics.append("TELEMETRY_TIMING_UNAVAILABLE")
    error_prone = _error_prone_operations(events)
    flags = _inefficiency_flags(slowest, error_prone)
    report_path = paths.efficiency_report_file
    report: EfficiencyReportPayload = {
        "status": "SUCCESS",
        "reason_code": "TELEMETRY_REPORT_READY",
        "repo": repo,
        "pr_number": str(pr_number),
        "coverage_label": coverage_label,
        "sources": sources,
        "total_events": total_events,
        "success_rate": success_rate,
        "total_observed_duration_ms": total_duration,
        "duration_observed": duration_observed,
        "telemetry_overhead_budget_ms": TELEMETRY_OVERHEAD_BUDGET_MS,
        "telemetry_overhead_ms": None,
        "host_metrics": host_metrics,
        "slowest_operations": [
            {
                "source": event.source,
                "operation": event.operation,
                "duration_ms": event.duration_ms,
                "status": event.status,
            }
            for event in slowest
        ],
        "error_prone_operations": error_prone,
        "inefficiency_flags": flags,
        "cli_health_issues": _cli_health_issues(paths=paths, events=events, diagnostics=diagnostics),
        "diagnostics": diagnostics,
        "confidence": _confidence_for_coverage(coverage_label),
        "report_generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_artifact": str(report_path),
    }
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(report_path, report)
    except OSError as exc:
        diagnostics.append(_safe_os_error_diagnostic("efficiency report artifact unavailable", exc))
    telemetry_overhead_ms = round((time.perf_counter() - overhead_started_at) * 1000, 3)
    report["telemetry_overhead_ms"] = telemetry_overhead_ms
    if telemetry_overhead_ms > TELEMETRY_OVERHEAD_BUDGET_MS and "TELEMETRY_OVERHEAD_EXCEEDED" not in diagnostics:
        diagnostics.append("TELEMETRY_OVERHEAD_EXCEEDED")
    return report


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
        "next_action": "RUN_TELEMETRY_SUMMARY" if status in {"SUCCESS", "PARTIAL"} else "FIX_TELEMETRY_INPUT",
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


def _load_import_diagnostics(paths: core_paths.SessionPaths) -> list[str]:
    path = paths.telemetry_imports_file
    if not path.exists():
        return []
    if not path.is_file():
        return [f"telemetry import summary is not a regular file: {path.name}"]
    diagnostics: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"telemetry import summary unreadable: {exc}"]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            diagnostics.append(f"telemetry import summary line {line_number}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(payload, dict):
            diagnostics.append(f"telemetry import summary line {line_number}: record must be a JSON object")
            continue
        if payload.get("status") == "SUCCESS" or payload.get("reason_code") == "DUPLICATE_TELEMETRY_IMPORT":
            continue
        raw_diagnostics = payload.get("diagnostics") or []
        if not isinstance(raw_diagnostics, list):
            diagnostics.append(f"telemetry import summary line {line_number}: diagnostics must be a list")
            continue
        for diagnostic in raw_diagnostics:
            diagnostics.append(f"telemetry import {payload.get('source', 'unknown')}: {diagnostic}")
    return diagnostics


def _has_unrecovered_import_diagnostics(paths: core_paths.SessionPaths) -> bool:
    path = paths.telemetry_imports_file
    if not path.exists():
        return False
    if not path.is_file():
        return True
    unrecovered_by_source: dict[str, bool] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return True
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return True
        if not isinstance(payload, dict):
            return True
        source = str(payload.get("source") or "unknown")
        status = payload.get("status")
        reason_code = payload.get("reason_code")
        if status == "SUCCESS":
            unrecovered_by_source[source] = False
        elif reason_code == "DUPLICATE_TELEMETRY_IMPORT":
            continue
        else:
            unrecovered_by_source[source] = True
    return any(unrecovered_by_source.values())


def _runtime_events(paths: core_paths.SessionPaths) -> list[ExternalTelemetryEvent]:
    tracker = SessionTelemetry()
    tracker.configure_file(paths.workspace_dir / "telemetry.jsonl")
    events: list[ExternalTelemetryEvent] = []
    for metric in tracker.metrics:
        event_id = (
            metric.execution_id
            or uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{metric.command}:{metric.start_time}:{metric.end_time}:{metric.exit_code}",
            ).hex
        )
        event = ExternalTelemetryEvent(
            schema_version="1.0",
            source="runtime",
            source_session_id=f"{paths.repo}#{paths.pr_number}",
            event_id=event_id,
            kind="command",
            operation=_safe_runtime_operation(metric.command),
            status="success" if metric.is_success else ("timeout" if metric.exit_code == 124 else "failure"),
            duration_ms=max(0, int(metric.duration * 1000)),
            started_at=datetime.fromtimestamp(metric.start_time, timezone.utc).isoformat().replace("+00:00", "Z"),
            ended_at=datetime.fromtimestamp(metric.end_time, timezone.utc).isoformat().replace("+00:00", "Z"),
            metadata={"exit_code": metric.exit_code, "is_retry": metric.is_retry},
        )
        events.append(ExternalTelemetryEvent(**{**event.to_dict(), "event_fingerprint": _event_fingerprint(event)}))
    return events
