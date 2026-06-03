from __future__ import annotations

import json
import os
import shlex
import uuid
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from gh_address_cr.core import paths as core_paths


def command_label(cmd: list[str]) -> str:
    """Return a public-safe command label for telemetry summaries."""
    cmd = _strip_inline_env_assignments(cmd)
    if not cmd:
        return ""

    label_tokens = [os.path.basename(cmd[0]) or cmd[0]]
    index = 1
    previous_was_flag = False
    if len(cmd) > 2 and label_tokens[0].startswith("python") and cmd[1] == "-m":
        label_tokens.extend(["-m", cmd[2]])
        index = 3
        previous_was_flag = False

    for token in cmd[index:]:
        if token == "--":
            break
        if token.startswith("-"):
            previous_was_flag = True
            continue
        if previous_was_flag:
            previous_was_flag = False
            continue
        if ":" in token:
            continue
        if "/" in token or "\\" in token or "=" in token:
            continue
        if any(marker.lower() in token.lower() for marker in TOKEN_MARKERS):
            continue
        label_tokens.append(token)
        break

    return shlex.join(label_tokens)


def _strip_inline_env_assignments(cmd: list[str]) -> list[str]:
    index = 0
    while index < len(cmd) and is_inline_env_assignment(cmd[index]):
        index += 1
    return cmd[index:]


def is_inline_env_assignment(token: str) -> bool:
    key, separator, _value = token.partition("=")
    return bool(separator and key and key.replace("_", "").isalnum() and not key[0].isdigit())


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

    def to_dict(self) -> dict:
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

MAX_DURATION_SECONDS = 60.0
MAX_ERROR_RATE_PERCENT = 20.0


@dataclass
class EfficiencyReport:
    total_invocations: int
    total_duration: float
    success_rate: float
    flagged_inefficiencies: list[str]
    metrics: list[ExecutionMetric]

    def to_dict(self) -> dict:
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
UNSAFE_METADATA_KEYS = {
    "token",
    "access_token",
    "authorization",
    "password",
    "secret",
    "credential",
    "raw_prompt",
    "prompt",
    "username",
    "user",
    "machine_id",
    "host_id",
}
UNSAFE_METADATA_KEY_MARKERS = (
    "token",
    "key",
    "authorization",
    "password",
    "secret",
    "credential",
    "prompt",
    "user",
    "machine",
    "host",
)
TOKEN_MARKERS = ("ghp_", "github_pat_", "Bearer ", "sk-", "xoxb-", "token=")


class SessionTelemetry:
    _instance: ClassVar[SessionTelemetry | None] = None

    def __init__(self):
        self.metrics: list[ExecutionMetric] = []
        self.telemetry_file: Path | None = None
        self._loaded_files: set[Path] = set()

    @classmethod
    def get_instance(cls) -> SessionTelemetry:
        if cls._instance is None:
            cls._instance = SessionTelemetry()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def configure_context(self, repo: str, pr_number: str) -> None:
        self.metrics.clear()
        self._loaded_files.clear()
        path = core_paths.workspace_dir(repo, pr_number) / "telemetry.jsonl"
        self.configure_file(path)

    def configure_file(self, path: Path) -> None:
        self.telemetry_file = path
        self._load_persisted_metrics(path)

    def _load_persisted_metrics(self, path: Path) -> None:
        if path in self._loaded_files:
            return
        self._loaded_files.add(path)
        try:
            if not path.is_file():
                return
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            metric = self._metric_from_payload(payload)
            if metric is not None:
                self.metrics.append(metric)

    @staticmethod
    def _metric_from_payload(payload: object) -> ExecutionMetric | None:
        if not isinstance(payload, dict):
            return None
        try:
            return ExecutionMetric(
                command=str(payload["command"]),
                start_time=float(payload["start_time"]),
                end_time=float(payload["end_time"]),
                exit_code=int(payload["exit_code"]),
                is_retry=bool(payload.get("is_retry", False)),
                pid=int(payload.get("pid", 0)),
                execution_id=str(payload.get("execution_id") or ""),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def record(
        self,
        command: str,
        start_time: float,
        end_time: float,
        exit_code: int,
        pid: int | None = None,
        execution_id: str | None = None,
    ) -> None:
        is_retry = False
        if self.metrics:
            last_metric = self.metrics[-1]
            if last_metric.command == command and not last_metric.is_success:
                is_retry = True

        metric = ExecutionMetric(
            command=command,
            start_time=start_time,
            end_time=end_time,
            exit_code=exit_code,
            is_retry=is_retry,
            pid=pid if pid is not None else os.getpid(),
            execution_id=execution_id if execution_id is not None else uuid.uuid4().hex,
        )
        self.metrics.append(metric)
        self._persist_metric(metric)

    def _persist_metric(self, metric: ExecutionMetric) -> None:
        if self.telemetry_file is None:
            return
        try:
            self.telemetry_file.parent.mkdir(parents=True, exist_ok=True)
            with self.telemetry_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(metric.to_dict(), sort_keys=True) + "\n")
        except OSError:
            return

    def evaluate_efficiency(self) -> list[str]:
        flags = []
        if not self.metrics:
            return flags

        def _display_command(command: str) -> str:
            if len(command) > 50:
                return f"{command[:50]}..."
            return command

        # 1. Individual Duration check
        for m in self.metrics:
            if m.duration > MAX_DURATION_SECONDS:
                flags.append(
                    f"`{_display_command(m.command)}` took {m.duration:.1f}s (Exceeds {int(MAX_DURATION_SECONDS)}s threshold)."
                )
            if m.exit_code == 124:
                flags.append(f"CRITICAL: `{_display_command(m.command)}` hit execution timeout (hung).")

        # 2. Global Error Rate check
        total_inv = len(self.metrics)
        successes = sum(1 for m in self.metrics if m.is_success)
        error_rate = ((total_inv - successes) / total_inv) * 100.0
        if error_rate > MAX_ERROR_RATE_PERCENT:
            flags.append(f"Global error rate is {error_rate:.1f}% (Exceeds {MAX_ERROR_RATE_PERCENT}% threshold).")

        # 3. Consecutive Retries check
        consecutive_retries: dict[str, int] = {}
        current_command: str | None = None
        current_retry_count = 0

        for m in self.metrics:
            if m.command != current_command:
                if current_command is not None:
                    consecutive_retries[current_command] = max(
                        consecutive_retries.get(current_command, 0),
                        current_retry_count,
                    )
                current_command = m.command
                current_retry_count = 0
            if m.is_retry:
                current_retry_count += 1

        if current_command is not None:
            consecutive_retries[current_command] = max(
                consecutive_retries.get(current_command, 0),
                current_retry_count,
            )

        for cmd, count in consecutive_retries.items():
            if count >= 1:
                retry_word = "retry" if count == 1 else "retries"
                flags.append(
                    f"`{_display_command(cmd)}` ran {count + 1} times consecutively with {count} {retry_word} (High Retry Rate)."
                )

        return flags

    def get_report(self) -> EfficiencyReport:
        total_inv = len(self.metrics)
        if total_inv == 0:
            return EfficiencyReport(0, 0.0, 0.0, [], [])

        total_dur = sum(m.duration for m in self.metrics)
        successes = sum(1 for m in self.metrics if m.is_success)
        success_rate = (successes / total_inv) * 100.0

        flags = self.evaluate_efficiency()

        return EfficiencyReport(
            total_invocations=total_inv,
            total_duration=total_dur,
            success_rate=success_rate,
            flagged_inefficiencies=flags,
            metrics=list(self.metrics),
        )

    def get_summary_string(self) -> str | None:
        if not self.metrics:
            return None

        report = self.get_report()
        summary = f"{report.total_invocations} tools invoked ({report.success_rate:.0f}% success). Total tool duration: {report.total_duration:.1f}s."

        if report.flagged_inefficiencies:
            summary += "\n> ⚠️ **Inefficiencies Detected**:\n"
            summary += "\n".join(f"> - {f}" for f in report.flagged_inefficiencies)

        return summary


def import_external_telemetry(repo: str, pr_number: str, *, source: str, fmt: str, raw: str) -> dict[str, Any]:
    if fmt != "agent-jsonl":
        summary = _import_summary(
            repo,
            pr_number,
            source=source,
            fmt=fmt,
            status="FAILED",
            reason_code="UNSUPPORTED_TELEMETRY_FORMAT",
            accepted_count=0,
            rejected_count=0,
            duplicate_count=0,
            accepted_fingerprints=[],
            duplicate_fingerprints=[],
            diagnostics=[f"Unsupported telemetry format: {fmt}"],
        )
        _append_import_summary(repo, pr_number, summary)
        return summary

    existing = _load_external_events(repo, pr_number)
    existing_fingerprints = _load_fingerprint_set(repo, pr_number)
    existing_fingerprints.update(event.identity for event in existing)
    accepted: list[ExternalTelemetryEvent] = []
    accepted_fingerprints: list[str] = []
    duplicate_fingerprints: list[str] = []
    diagnostics: list[str] = []
    observed_sessions: set[str] = set()
    rejected_count = 0
    duplicate_count = 0
    unsafe_seen = False
    malformed_seen = False

    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            malformed_seen = True
            rejected_count += 1
            diagnostics.append(f"line {line_number}: invalid JSON: {exc.msg}")
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
        observed_sessions.add(event.source_session_id)
        if event.identity in existing_fingerprints:
            duplicate_count += 1
            duplicate_fingerprints.append(event.identity)
            continue
        existing_fingerprints.add(event.identity)
        accepted_fingerprints.append(event.identity)
        accepted.append(event)

    ambiguous_seen = len(observed_sessions) > 1
    if unsafe_seen:
        accepted = []
        accepted_fingerprints = []
    if ambiguous_seen:
        diagnostics.append("ambiguous telemetry session: multiple source_session_id values in one import")
        rejected_count += len(accepted)
        accepted = []
        accepted_fingerprints = []

    if ambiguous_seen:
        status = "FAILED"
        reason_code = "AMBIGUOUS_TELEMETRY_SESSION"
    elif unsafe_seen:
        status = "FAILED"
        reason_code = "UNSAFE_TELEMETRY_CONTENT"
    elif accepted:
        status = "SUCCESS" if rejected_count == 0 else "PARTIAL"
        reason_code = "TELEMETRY_IMPORTED" if rejected_count == 0 else "TELEMETRY_PARTIAL"
    elif duplicate_count and not rejected_count:
        status = "FAILED"
        reason_code = "DUPLICATE_TELEMETRY_IMPORT"
        diagnostics.append("All telemetry events were duplicates.")
    elif malformed_seen:
        status = "FAILED"
        reason_code = "MALFORMED_TELEMETRY"
    else:
        status = "FAILED"
        reason_code = "MALFORMED_TELEMETRY"
        diagnostics.append("No telemetry events were provided.")

    if accepted and status in {"SUCCESS", "PARTIAL"}:
        _append_external_events(repo, pr_number, accepted)
        _write_fingerprint_set(repo, pr_number, existing_fingerprints)

    summary = _import_summary(
        repo,
        pr_number,
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
    _append_import_summary(repo, pr_number, summary)
    return summary


def build_efficiency_report(repo: str, pr_number: str) -> dict[str, Any]:
    runtime_events = _runtime_events(repo, pr_number)
    external_events, diagnostics = _load_external_events_with_diagnostics(repo, pr_number)
    diagnostics.extend(_load_import_diagnostics(repo, pr_number))
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
    coverage_label = _coverage_label(runtime_events, external_events)
    total_events = len(events)
    known_status_events = [event for event in events if event.status != "unknown"]
    success_count = sum(1 for event in known_status_events if event.status == "success")
    success_rate = (success_count / len(known_status_events)) * 100.0 if known_status_events else 0.0
    total_duration = sum(event.duration_ms for event in events)
    slowest = sorted(events, key=lambda event: event.duration_ms, reverse=True)[:3]
    error_prone = _error_prone_operations(events)
    flags = _inefficiency_flags(slowest, error_prone)
    report_path = core_paths.efficiency_report_file(repo, pr_number)
    report = {
        "status": "SUCCESS",
        "reason_code": "TELEMETRY_REPORT_READY",
        "repo": repo,
        "pr_number": str(pr_number),
        "coverage_label": coverage_label,
        "sources": sources,
        "total_events": total_events,
        "success_rate": success_rate,
        "total_observed_duration_ms": total_duration,
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
        "diagnostics": diagnostics,
        "confidence": _confidence_for_coverage(coverage_label),
        "report_generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_artifact": str(report_path),
    }
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        report["diagnostics"].append(f"efficiency report artifact unavailable: {type(exc).__name__}: {exc}")
    return report


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
    if report["inefficiency_flags"]:
        lines.extend(["", "### Inefficiency Flags"])
        lines.extend(f"- {flag}" for flag in report["inefficiency_flags"])
    if report.get("diagnostics"):
        lines.extend(["", "### Diagnostics"])
        lines.extend(f"- {diagnostic}" for diagnostic in report["diagnostics"])
    return "\n".join(lines) + "\n"


def _normalize_external_event(payload: object, *, declared_source: str) -> ExternalTelemetryEvent:
    if not isinstance(payload, dict):
        raise ValueError("record must be a JSON object")
    source = _safe_source_label(str(payload.get("source") or declared_source))
    required = ("kind", "operation", "status")
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
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
    operation = _safe_operation(str(payload["operation"]))
    started_at = _safe_optional_timestamp(payload.get("started_at"), field="started_at")
    ended_at = _safe_optional_timestamp(payload.get("ended_at"), field="ended_at")
    correlation_id = _safe_identity_label(str(payload["correlation_id"]), field="correlation_id") if payload.get("correlation_id") else None
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
        try:
            value = int(payload["duration_ms"])
        except (TypeError, ValueError):
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


def _safe_metadata(metadata: object) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    _validate_safe_metadata_value(metadata)
    return {str(key): value for key, value in metadata.items()}


def _validate_safe_metadata_value(value: object, *, key_path: str = "metadata") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            lowered_key = key_text.lower()
            if lowered_key in UNSAFE_METADATA_KEYS or any(marker in lowered_key for marker in UNSAFE_METADATA_KEY_MARKERS):
                raise ValueError(f"UNSAFE:unsafe metadata field: {key_text}")
            _validate_safe_metadata_value(nested, key_path=f"{key_path}.{key_text}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_safe_metadata_value(item, key_path=f"{key_path}[{index}]")
        return
    value_text = str(value)
    lowered_value = value_text.lower()
    if any(marker.lower() in lowered_value for marker in TOKEN_MARKERS):
        raise ValueError(f"UNSAFE:unsafe metadata value at {key_path}")
    if _looks_like_unnecessary_absolute_path(value_text):
        raise ValueError(f"UNSAFE:unsafe absolute path in metadata value at {key_path}")


def _safe_operation(operation: str) -> str:
    if any(marker.lower() in operation.lower() for marker in TOKEN_MARKERS):
        raise ValueError("UNSAFE:unsafe operation label")
    if _looks_like_unnecessary_absolute_path(operation):
        raise ValueError("UNSAFE:unsafe absolute path in operation label")
    return operation


def _safe_source_label(source: str) -> str:
    lowered = source.lower()
    if any(marker.lower() in lowered for marker in TOKEN_MARKERS):
        raise ValueError("UNSAFE:unsafe source label")
    if _looks_like_unnecessary_absolute_path(source):
        raise ValueError("UNSAFE:unsafe absolute path in source label")
    return source


def _safe_source_session_id(source_session_id: str) -> str:
    lowered = source_session_id.lower()
    if any(marker.lower() in lowered for marker in TOKEN_MARKERS):
        raise ValueError("UNSAFE:unsafe source_session_id")
    if any(marker in lowered for marker in ("username", "user-", "machine", "host_id", "host-")):
        raise ValueError("UNSAFE:unsafe source_session_id")
    if _looks_like_unnecessary_absolute_path(source_session_id):
        raise ValueError("UNSAFE:unsafe absolute path in source_session_id")
    return source_session_id


def _safe_identity_label(value: str, *, field: str) -> str:
    lowered = value.lower()
    if any(marker.lower() in lowered for marker in TOKEN_MARKERS):
        raise ValueError(f"UNSAFE:unsafe {field}")
    if _looks_like_unnecessary_absolute_path(value):
        raise ValueError(f"UNSAFE:unsafe absolute path in {field}")
    return value


def _safe_optional_timestamp(value: object, *, field: str) -> str | None:
    if not value:
        return None
    text = str(value)
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in TOKEN_MARKERS):
        raise ValueError(f"UNSAFE:unsafe {field}")
    if _looks_like_unnecessary_absolute_path(text):
        raise ValueError(f"UNSAFE:unsafe absolute path in {field}")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be an ISO timestamp") from None
    return text


def _safe_runtime_operation(operation: str) -> str:
    lowered = operation.lower()
    if any(marker.lower() in lowered for marker in TOKEN_MARKERS) or _looks_like_unnecessary_absolute_path(operation):
        try:
            return command_label(shlex.split(operation)) or "runtime command"
        except ValueError:
            return "runtime command"
    return operation


def _looks_like_unnecessary_absolute_path(value: str) -> bool:
    lowered = value.lower()
    return (
        "/users/" in lowered
        or "/private/" in lowered
        or "/home/" in lowered
        or "/root/" in lowered
        or "c:\\users\\" in lowered
    )


def _load_external_events(repo: str, pr_number: str) -> list[ExternalTelemetryEvent]:
    events, _diagnostics = _load_external_events_with_diagnostics(repo, pr_number)
    return events


def _load_external_events_with_diagnostics(repo: str, pr_number: str) -> tuple[list[ExternalTelemetryEvent], list[str]]:
    path = core_paths.external_telemetry_file(repo, pr_number)
    if not path.is_file():
        return [], []
    events: list[ExternalTelemetryEvent] = []
    diagnostics: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"external telemetry unreadable: {exc}"]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            events.append(_normalize_external_event(payload, declared_source=str(payload.get("source") or "")))
        except json.JSONDecodeError as exc:
            diagnostics.append(f"external telemetry line {line_number}: invalid JSON: {exc.msg}")
        except ValueError as exc:
            diagnostics.append(f"external telemetry line {line_number}: {exc}")
    return events, diagnostics


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
        if key and key in seen and seen[key].source != event.source:
            diagnostics.append(f"correlated telemetry event ignored: {event.source}:{event.event_id}")
            continue
        if key:
            seen[key] = event
        deduped.append(event)
    return deduped, diagnostics


def _correlation_dedupe_key(event: ExternalTelemetryEvent) -> str | None:
    correlation = event.correlation_id or (event.event_id if event.source == "runtime" else None)
    if not correlation:
        return None
    return f"{correlation}:{event.operation}:{event.status}"


def _load_fingerprint_set(repo: str, pr_number: str) -> set[str]:
    path = core_paths.telemetry_fingerprints_file(repo, pr_number)
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    fingerprints = payload.get("event_fingerprints")
    if not isinstance(fingerprints, list):
        return set()
    return {str(value) for value in fingerprints if value}


def _write_fingerprint_set(repo: str, pr_number: str, fingerprints: set[str]) -> None:
    path = core_paths.telemetry_fingerprints_file(repo, pr_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"event_fingerprints": sorted(fingerprints)}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_external_events(repo: str, pr_number: str, events: list[ExternalTelemetryEvent]) -> None:
    path = core_paths.external_telemetry_file(repo, pr_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")


def _append_import_summary(repo: str, pr_number: str, summary: dict[str, Any]) -> None:
    path = core_paths.telemetry_imports_file(repo, pr_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, sort_keys=True) + "\n")


def _import_summary(
    repo: str,
    pr_number: str,
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
        "repo": repo,
        "pr_number": str(pr_number),
        "source": _reported_source_label(source),
        "format": fmt,
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
    lowered = source.lower()
    if any(marker.lower() in lowered for marker in TOKEN_MARKERS):
        return "[redacted]"
    if _looks_like_unnecessary_absolute_path(source):
        return "[redacted]"
    return source


def _load_import_diagnostics(repo: str, pr_number: str) -> list[str]:
    path = core_paths.telemetry_imports_file(repo, pr_number)
    if not path.is_file():
        return []
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
        if payload.get("status") == "SUCCESS" or payload.get("reason_code") == "DUPLICATE_TELEMETRY_IMPORT":
            continue
        for diagnostic in payload.get("diagnostics") or []:
            diagnostics.append(f"telemetry import {payload.get('source', 'unknown')}: {diagnostic}")
    return diagnostics


def _runtime_events(repo: str, pr_number: str) -> list[ExternalTelemetryEvent]:
    tracker = SessionTelemetry()
    tracker.configure_file(core_paths.workspace_dir(repo, pr_number) / "telemetry.jsonl")
    events: list[ExternalTelemetryEvent] = []
    for metric in tracker.metrics:
        event_id = metric.execution_id or uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{metric.command}:{metric.start_time}:{metric.end_time}:{metric.exit_code}",
        ).hex
        event = ExternalTelemetryEvent(
            schema_version="1.0",
            source="runtime",
            source_session_id=f"{repo}#{pr_number}",
            event_id=event_id,
            kind="command",
            operation=_safe_runtime_operation(metric.command),
            status="success" if metric.is_success else ("timeout" if metric.exit_code == 124 else "failure"),
            duration_ms=max(0, int(metric.duration * 1000)),
            metadata={"exit_code": metric.exit_code, "is_retry": metric.is_retry},
        )
        events.append(ExternalTelemetryEvent(**{**event.to_dict(), "event_fingerprint": _event_fingerprint(event)}))
    return events


def _coverage_label(runtime_events: list[ExternalTelemetryEvent], external_events: list[ExternalTelemetryEvent]) -> str:
    if runtime_events and external_events:
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
        if row["failures"] or row["retries"] or row["timeouts"]:
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
