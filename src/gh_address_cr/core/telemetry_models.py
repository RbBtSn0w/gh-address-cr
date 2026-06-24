"""Shared telemetry data types and thresholds.

This leaf module holds the dataclasses, ``TypedDict`` payload shapes, and
threshold constants that the telemetry runtime (`telemetry.py`) and the
reporting layer (`telemetry_reporting.py`) both depend on. Keeping them here
breaks what would otherwise be a circular import between those two modules and
gives the decomposition (#153) a single source of truth for serialization
shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

# Inefficiency thresholds shared by the runtime summary (SessionTelemetry) and
# the external-event reporting helpers.
MAX_DURATION_SECONDS = 60.0
MAX_ERROR_RATE_PERCENT = 20.0


@dataclass
class ExecutionMetric:
    command: str
    start_time: float
    end_time: float
    exit_code: int
    is_retry: bool = False
    pid: int = 0
    execution_id: str = ""

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def is_success(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "exit_code": self.exit_code,
            "is_success": self.is_success,
            "is_retry": self.is_retry,
            "pid": self.pid,
            "execution_id": self.execution_id,
        }


@dataclass
class EfficiencyReport:
    total_invocations: int
    total_duration: float
    success_rate: float
    flagged_inefficiencies: list[str]
    metrics: list[ExecutionMetric]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_invocations": self.total_invocations,
            "total_duration": self.total_duration,
            "success_rate": self.success_rate,
            "flagged_inefficiencies": self.flagged_inefficiencies,
            "metrics": [m.to_dict() for m in self.metrics],
        }


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


SAFE_STATUSES = {"success", "failure", "timeout", "cancelled", "unknown"}
SAFE_KINDS = {"tool_call", "command", "wait", "retry", "validation", "agent_step"}


class SlowestOperation(TypedDict):
    source: str
    operation: str
    duration_ms: int
    status: str


class EfficiencyReportPayload(TypedDict):
    status: str
    reason_code: str
    repo: str
    pr_number: str
    coverage_label: str
    sources: list[dict[str, Any]]
    total_events: int
    success_rate: float
    total_observed_duration_ms: int
    duration_observed: bool
    telemetry_overhead_budget_ms: int
    telemetry_overhead_ms: float | None
    host_metrics: dict[str, int]
    slowest_operations: list[SlowestOperation]
    error_prone_operations: list[dict[str, Any]]
    inefficiency_flags: list[str]
    cli_health_issues: list[dict[str, Any]]
    diagnostics: list[str]
    confidence: str
    report_generated_at: str
    report_artifact: str


@dataclass
class TelemetryParseResult:
    events: list[ExternalTelemetryEvent]
    rejected_count: int
    unsafe_seen: bool
    malformed_seen: bool
    diagnostics: list[Any]
    events_are_normalized: bool = False
