from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.telemetry_attribution import (
    ExternalTelemetryEvent,
    _dedupe_correlated_events,
    _dedupe_events,
    _load_external_events_with_diagnostics,
)
from gh_address_cr.core.telemetry_safety import (
    _safe_diagnostic_text,
    _safe_metadata,
)

TELEMETRY_OVERHEAD_BUDGET_MS = 250

def build_efficiency_report(repo: str, pr_number: str) -> dict[str, Any]:
    from gh_address_cr.core import telemetry
    overhead_started_at = time.perf_counter()
    paths = core_paths.SessionPaths(repo, pr_number)

    runtime_events = telemetry._runtime_events(paths)
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
    duration_observed = any(event.duration_ms > 0 for event in events)
    host_metrics = _aggregate_host_metrics(external_events)
    timed_events = [event for event in events if event.duration_ms > 0]
    slowest = sorted(timed_events, key=lambda event: event.duration_ms, reverse=True)[:3]
    if events and not duration_observed and "TELEMETRY_TIMING_UNAVAILABLE" not in diagnostics:
        diagnostics.append("TELEMETRY_TIMING_UNAVAILABLE")
    error_prone = _error_prone_operations(events, max_error_rate_percent=telemetry.MAX_ERROR_RATE_PERCENT)
    flags = _inefficiency_flags(slowest, error_prone, max_duration_seconds=telemetry.MAX_DURATION_SECONDS)
    report_path = paths.efficiency_report_file
    report: dict[str, Any] = {
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
        diagnostics.append(telemetry._safe_os_error_diagnostic("efficiency report artifact unavailable", exc))
    telemetry_overhead_ms = round((time.perf_counter() - overhead_started_at) * 1000, 3)
    report["telemetry_overhead_ms"] = telemetry_overhead_ms
    if telemetry_overhead_ms > TELEMETRY_OVERHEAD_BUDGET_MS and "TELEMETRY_OVERHEAD_EXCEEDED" not in diagnostics:
        diagnostics.append("TELEMETRY_OVERHEAD_EXCEEDED")
    return report

def _aggregate_host_metrics(events: list[ExternalTelemetryEvent]) -> dict[str, int]:
    totals = {
        "token_input_count": 0,
        "token_output_count": 0,
        "token_total_count": 0,
        "tool_call_count": 0,
    }
    for event in events:
        metadata = event.metadata or {}
        if not isinstance(metadata, dict):
            continue
        for key in totals:
            value = metadata.get(key)
            if isinstance(value, int) and value >= 0:
                totals[key] += value
    return {key: value for key, value in totals.items() if value}

def efficiency_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "## Agent Efficiency Summary",
        "",
        f"- coverage_label: {report['coverage_label']}",
        f"- total_events: {report['total_events']}",
        f"- success_rate: {report['success_rate']:.1f}%",
        f"- total_observed_duration_ms: {report['total_observed_duration_ms']}",
        f"- report_artifact: {report['report_artifact']}",
        f"- confidence: {report.get('confidence', 'low')}",
        "",
        "### Sources",
    ]
    lines.extend(
        f"- {source['source']} ({source['source_type']}): {source['event_count']} events, {source['coverage_status']}"
        for source in report["sources"]
    )
    if report["slowest_operations"]:
        lines.extend(["", "### Slowest Operations"])
        lines.extend(
            f"- {row['operation']} [{row['source']}]: {row['duration_ms']}ms ({row['status']})"
            for row in report["slowest_operations"]
        )
    elif report["total_events"] and not report.get("duration_observed", True):
        lines.extend(["", "_Note: operation timing was not reported; duration analysis is unavailable._"])
    if report["inefficiency_flags"]:
        lines.extend(["", "### Inefficiency Flags"])
        lines.extend(f"- {flag}" for flag in report["inefficiency_flags"])
    if report.get("diagnostics"):
        lines.extend(["", "### Diagnostics"])
        lines.extend(f"- {diagnostic}" for diagnostic in report["diagnostics"])
    return "\n".join(lines) + "\n"

def _cli_health_issues(
    *,
    paths: core_paths.SessionPaths,
    events: list[ExternalTelemetryEvent],
    diagnostics: list[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(
        reason_code: str,
        severity: str,
        source: str,
        retryable: bool,
        detail: str,
        next_action: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        key = (reason_code, detail)
        if key in seen:
            return
        seen.add(key)
        issue = {
            "reason_code": reason_code,
            "severity": severity,
            "source": source,
            "retryable": retryable,
            "detail": _safe_diagnostic_text(detail),
            "next_action": next_action,
        }
        if metadata:
            issue["metadata"] = _safe_metadata(metadata)
        issues.append(issue)

    from gh_address_cr.core import telemetry
    summary_issue = telemetry._last_machine_summary_health_issue(paths)
    if summary_issue is not None:
        add(**summary_issue)

    for event in events:
        if event.source != "runtime":
            continue
        if event.status == "timeout":
            add(
                "CLI_COMMAND_TIMEOUT",
                "warning",
                "runtime",
                True,
                f"{event.operation} timed out.",
                "Inspect the timed-out CLI dependency and retry after it responds.",
            )
        elif event.status == "failure":
            add(
                "CLI_COMMAND_FAILURE",
                "warning",
                "runtime",
                True,
                f"{event.operation} exited with failure.",
                "Inspect the command output and rerun the failed gh-address-cr workflow step.",
            )
        metadata = event.metadata or {}
        if metadata.get("is_retry"):
            add(
                "CLI_RETRY_LOOP",
                "warning",
                "runtime",
                True,
                f"{event.operation} was retried.",
                "Check whether the command failure is deterministic before retrying again.",
            )

    for diagnostic in diagnostics:
        if "host telemetry autodiscovery" in diagnostic:
            add(
                "TELEMETRY_AUTODISCOVERY_MISS",
                "info",
                "host-autodiscovery",
                True,
                diagnostic,
                "Run telemetry doctor to inspect profile environment, transcript discovery, and PR attribution.",
            )
        elif "telemetry input unavailable" in diagnostic:
            add(
                "TELEMETRY_STORE_UNAVAILABLE",
                "warning",
                "telemetry-store",
                True,
                diagnostic,
                "Provide a readable telemetry input path or rerun from an agent host with telemetry enabled.",
            )
        elif "telemetry import summary" in diagnostic or "external telemetry" in diagnostic:
            add(
                "TELEMETRY_STORE_UNAVAILABLE",
                "warning",
                "telemetry-store",
                True,
                diagnostic,
                "Repair or remove the malformed telemetry artifact, then rerun telemetry summary.",
            )
        elif diagnostic == "TELEMETRY_TIMING_UNAVAILABLE":
            add(
                "TELEMETRY_TIMING_UNAVAILABLE",
                "info",
                "runtime",
                False,
                diagnostic,
                "Use sources that provide operation durations for timing analysis.",
            )
    return issues

def _coverage_label(
    runtime_events: list[ExternalTelemetryEvent],
    external_events: list[ExternalTelemetryEvent],
    import_diagnostics: list[str] | None = None,
) -> str:
    if runtime_events and external_events:
        if import_diagnostics:
            return "partial"
        return "complete"
    if external_events:
        return "partial"
    if runtime_events:
        return "runtime-only"
    return "unavailable"

def _source_rows(
    runtime_events: list[ExternalTelemetryEvent],
    external_events: list[ExternalTelemetryEvent],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if runtime_events:
        rows.append(
            {
                "source": "runtime",
                "source_type": "runtime",
                "coverage_status": "available",
                "event_count": len(runtime_events),
                "notes": "Runtime telemetry was available.",
            }
        )
    grouped: dict[str, int] = {}
    for event in external_events:
        grouped[event.source] = grouped.get(event.source, 0) + 1
    for source, count in sorted(grouped.items()):
        rows.append(
            {
                "source": source,
                "source_type": "generic-agent" if source == "generic-agent" else "host-adapter",
                "coverage_status": "available",
                "event_count": count,
                "notes": "Imported external telemetry was available.",
            }
        )
    if not rows:
        rows.append(
            {
                "source": "telemetry",
                "source_type": "runtime",
                "coverage_status": "unavailable",
                "event_count": 0,
                "notes": "No usable telemetry was available.",
            }
        )
    return rows

def _error_prone_operations(events: list[ExternalTelemetryEvent], *, max_error_rate_percent: float) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        row = grouped.setdefault(
            event.operation,
            {"operation": event.operation, "events": 0, "failures": 0, "retries": 0, "timeouts": 0, "sources": set()},
        )
        row["events"] += 1
        row["sources"].add(event.source)
        if event.status in {"failure", "cancelled"}:
            row["failures"] += 1
        if event.status == "timeout":
            row["timeouts"] += 1
        if event.kind == "retry" or (event.metadata or {}).get("is_retry"):
            row["retries"] += 1
    result: list[dict[str, Any]] = []
    for row in grouped.values():
        problem_count = row["failures"] + row["retries"] + row["timeouts"]
        problem_rate = (problem_count / row["events"]) * 100.0 if row["events"] else 0.0
        if problem_rate > max_error_rate_percent:
            result.append(
                {
                    "operation": row["operation"],
                    "events": row["events"],
                    "failures": row["failures"],
                    "retries": row["retries"],
                    "timeouts": row["timeouts"],
                    "sources": sorted(row["sources"]),
                }
            )
    return sorted(result, key=lambda row: (row["failures"] + row["retries"] + row["timeouts"], row["events"]), reverse=True)

def _inefficiency_flags(slowest: list[ExternalTelemetryEvent], error_prone: list[dict[str, Any]], *, max_duration_seconds: float) -> list[str]:
    flags: list[str] = []
    for event in slowest:
        if event.duration_ms > int(max_duration_seconds * 1000):
            flags.append(f"{event.operation} exceeded {int(max_duration_seconds)}s threshold.")
    for row in error_prone:
        flags.append(
            f"{row['operation']} had {row['failures']} failures, {row['timeouts']} timeouts, and {row['retries']} retries."
        )
    return flags

def _confidence_for_coverage(coverage_label: str) -> str:
    if coverage_label == "complete":
        return "high"
    if coverage_label in {"partial", "runtime-only"}:
        return "medium"
    return "low"

def _load_import_diagnostics(paths: core_paths.SessionPaths) -> list[str]:
    import json
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
    import json
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
