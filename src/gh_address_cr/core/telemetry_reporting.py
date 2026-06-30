"""Telemetry reporting helpers: efficiency-report derivation, CLI health, markdown.

These functions operate on already-loaded :class:`ExternalTelemetryEvent`
values and session paths; they perform no event persistence and never touch the
stateful ``SessionTelemetry`` runtime. ``telemetry.build_efficiency_report``
loads/dedupes events and delegates the pure computation and formatting here, so
the dependency stays one-directional (``telemetry`` -> ``telemetry_reporting``)
and free of cycles (#153 / #158).
"""

from __future__ import annotations

import json
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.telemetry_models import (
    MAX_DURATION_SECONDS,
    MAX_ERROR_RATE_PERCENT,
    ExternalTelemetryEvent,
)
from gh_address_cr.core.telemetry_safety import _safe_diagnostic_text, _safe_metadata


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

    summary_issue = _last_machine_summary_health_issue(paths)
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


def _last_machine_summary_health_issue(paths: core_paths.SessionPaths) -> dict[str, Any] | None:
    path = core_paths.last_machine_summary_file(paths.repo, paths.pr_number)
    if not path.exists():
        return None
    if not path.is_file():
        return {
            "reason_code": "TELEMETRY_STORE_UNAVAILABLE",
            "severity": "warning",
            "source": "runtime-summary",
            "retryable": True,
            "detail": "last machine summary is not a regular file",
            "next_action": "Repair or remove the malformed last-machine-summary artifact, then rerun telemetry doctor.",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {
            "reason_code": "TELEMETRY_STORE_UNAVAILABLE",
            "severity": "warning",
            "source": "runtime-summary",
            "retryable": True,
            "detail": f"last machine summary unreadable: {type(exc).__name__}",
            "next_action": "Repair the runtime summary artifact, then rerun telemetry doctor.",
        }
    except ValueError:
        return {
            "reason_code": "TELEMETRY_STORE_UNAVAILABLE",
            "severity": "warning",
            "source": "runtime-summary",
            "retryable": True,
            "detail": "last machine summary invalid JSON",
            "next_action": "Repair or remove the malformed last-machine-summary artifact, then rerun telemetry doctor.",
        }
    if not isinstance(payload, dict):
        return {
            "reason_code": "TELEMETRY_STORE_UNAVAILABLE",
            "severity": "warning",
            "source": "runtime-summary",
            "retryable": True,
            "detail": "last machine summary must be a JSON object",
            "next_action": "Repair or remove the malformed last-machine-summary artifact, then rerun telemetry doctor.",
        }
    status = str(payload.get("status") or "UNKNOWN")
    observed_reason = str(payload.get("reason_code") or "UNKNOWN_REASON")
    if status == "PASSED" or observed_reason == "PASSED":
        return None
    next_action = str(payload.get("next_action") or "Inspect the last CLI machine summary and rerun the workflow.")
    waiting_on = payload.get("waiting_on")
    if status.startswith("WAITING") or waiting_on:
        reason_code = "CLI_WAIT_STATE"
        severity = "info"
        retryable = True
    elif status in {"FAILED", "BLOCKED"}:
        reason_code = "CLI_COMMAND_FAILURE"
        severity = "warning"
        retryable = True
    else:
        reason_code = "CLI_REASON_CODE_OBSERVED"
        severity = "info"
        retryable = True
    detail = f"CLI summary reported {observed_reason}."
    return {
        "reason_code": reason_code,
        "severity": severity,
        "source": "runtime-summary",
        "retryable": retryable,
        "detail": detail,
        "next_action": next_action,
        "metadata": {
            "observed_reason_code": observed_reason,
            "observed_status": status,
            "waiting_on": str(waiting_on) if waiting_on else "",
        },
    }


def _safe_os_error_diagnostic(prefix: str, exc: OSError) -> str:
    detail = exc.strerror or str(exc)
    return f"{prefix}: {type(exc).__name__}: {detail}"


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


def _error_prone_operations(events: list[ExternalTelemetryEvent]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        op = event.operation
        if op not in grouped:
            grouped[op] = {
                "operation": op,
                "events": 0,
                "failures": 0,
                "retries": 0,
                "timeouts": 0,
                "sources": set(),
            }
        row = grouped[op]
        row["events"] += 1
        row["sources"].add(event.source)

        status = event.status
        if status == "failure" or status == "cancelled":
            row["failures"] += 1
        elif status == "timeout":
            row["timeouts"] += 1

        if event.kind == "retry" or (event.metadata and event.metadata.get("is_retry")):
            row["retries"] += 1
    result: list[dict[str, Any]] = []
    for row in grouped.values():
        problem_count = row["failures"] + row["retries"] + row["timeouts"]
        problem_rate = (problem_count / row["events"]) * 100.0 if row["events"] else 0.0
        if problem_rate > MAX_ERROR_RATE_PERCENT:
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
    return sorted(
        result, key=lambda row: (row["failures"] + row["retries"] + row["timeouts"], row["events"]), reverse=True
    )


def _inefficiency_flags(slowest: list[ExternalTelemetryEvent], error_prone: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    for event in slowest:
        if event.duration_ms > int(MAX_DURATION_SECONDS * 1000):
            flags.append(f"{event.operation} exceeded {int(MAX_DURATION_SECONDS)}s threshold.")
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
