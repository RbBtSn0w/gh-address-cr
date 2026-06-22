from __future__ import annotations

import json
import math
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, ClassVar

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core import protocol_codes
from gh_address_cr.core.command_runner import telemetry_debug_enabled
from gh_address_cr.core.io import write_json_atomic

# Content-safety/redaction helpers live in a dedicated module; re-exported here so
# existing `telemetry.<name>` references (including tests) keep resolving.
from gh_address_cr.core.telemetry_safety import (  # noqa: F401
    TOKEN_MARKERS,
    UNSAFE_METADATA_KEY_MARKERS,
    UNSAFE_METADATA_KEYS,
    _contains_control_character,
    _contains_private_identifier,
    _contains_token_marker,
    _is_unsafe_metadata_key,
    _json_loads_strict,
    _looks_like_unnecessary_absolute_path,
    _reject_json_constant,
    _safe_correlation_id,
    _safe_diagnostic_text,
    _safe_identity_label,
    _safe_metadata,
    _safe_operation,
    _safe_optional_timestamp,
    _safe_runtime_operation,
    _safe_source_label,
    _safe_source_session_id,
    _strip_inline_env_assignments,
    _validate_safe_metadata_value,
    command_label,
    is_inline_env_assignment,
    split_inline_env_assignments,
)


def _log_telemetry_failure(action: str, exc: BaseException) -> None:
    """Telemetry is best-effort; never raise into callers, but surface under the debug flag."""
    if telemetry_debug_enabled():
        import sys

        sys.stderr.write(f"Telemetry {action} failed: {type(exc).__name__}: {exc}\n")


def configure_context_safely(repo: str, pr_number: str) -> None:
    """Configure the telemetry session context without ever raising into the caller."""
    try:
        SessionTelemetry.get_instance().configure_context(repo, str(pr_number))
    except Exception as exc:  # intentionally broad: telemetry must not break core flows
        _log_telemetry_failure("context configuration", exc)


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


def _normalize_host_status(value: Any) -> str:
    status = str(value or "unknown").lower()
    return status if status in SAFE_STATUSES else "unknown"


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


register_adapter("agent-jsonl", GenericAgentJsonlAdapter())
register_adapter("codex-host-json", CodexHostJsonAdapter(), source="codex")


class SessionTelemetry:
    _instance: ClassVar[SessionTelemetry | None] = None

    def __init__(self):
        self.metrics: list[ExecutionMetric] = []
        self.telemetry_file: Path | None = None
        self._loaded_files: set[Path] = set()
        self.paths: core_paths.SessionPaths | None = None

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
        self.paths = core_paths.SessionPaths(repo, pr_number)
        path = self.paths.workspace_dir / "telemetry.jsonl"
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
            loaded_metrics: list[ExecutionMetric] = []
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    metric = self._metric_from_payload(payload)
                    if metric is not None:
                        loaded_metrics.append(metric)
            self.metrics.extend(loaded_metrics)
        except OSError:
            return

    @staticmethod
    def _metric_from_payload(payload: object) -> ExecutionMetric | None:
        if not isinstance(payload, dict):
            return None
        try:
            start_time = float(payload["start_time"])
            end_time = float(payload["end_time"])
            if not math.isfinite(start_time) or not math.isfinite(end_time):
                return None
            return ExecutionMetric(
                command=str(payload["command"]),
                start_time=start_time,
                end_time=end_time,
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


def _failed_import_summary(
    paths,
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
    accepted: list,
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


def _load_import_state(paths, *, source: str, fmt: str):
    """Load existing events + fingerprints, returning a failure summary if storage is corrupt.

    Returns ``(existing, existing_fingerprints, None)`` on success, or
    ``(None, None, failure_summary)`` when any precondition fails.
    """
    existing, storage_diagnostics = _load_external_events_with_diagnostics(paths)
    if storage_diagnostics:
        return None, None, _failed_import_summary(
            paths, source=source, fmt=fmt, reason_code="CORRUPTED_TELEMETRY_STORE", diagnostics=storage_diagnostics
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
    if load_failure is not None:
        return load_failure

    try:
        parse_result = adapter.parse(raw, source)
        if not isinstance(parse_result, TelemetryParseResult):
            raise TypeError(f"Adapter parse must return a TelemetryParseResult instance, got {type(parse_result).__name__}")
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

    accepted: list[ExternalTelemetryEvent] = []
    accepted_fingerprints: list[str] = []
    duplicate_fingerprints: list[str] = []
    observed_sessions: set[str] = set()
    duplicate_count = 0
    trusted_normalized_events = parse_result.events_are_normalized and type(adapter) is GenericAgentJsonlAdapter

    try:
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


TELEMETRY_OVERHEAD_BUDGET_MS = 250


def build_efficiency_report(repo: str, pr_number: str) -> dict[str, Any]:
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
    duration_observed = any(event.duration_ms > 0 for event in events)
    host_metrics = _aggregate_host_metrics(external_events)
    timed_events = [event for event in events if event.duration_ms > 0]
    slowest = sorted(timed_events, key=lambda event: event.duration_ms, reverse=True)[:3]
    if events and not duration_observed and "TELEMETRY_TIMING_UNAVAILABLE" not in diagnostics:
        diagnostics.append("TELEMETRY_TIMING_UNAVAILABLE")
    error_prone = _error_prone_operations(events)
    flags = _inefficiency_flags(slowest, error_prone)
    report_path = paths.efficiency_report_file
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
        "diagnostics": diagnostics,
        "confidence": _confidence_for_coverage(coverage_label),
        "report_generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_artifact": str(report_path),
    }
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(report_path, report)
    except OSError as exc:
        report["diagnostics"].append(_safe_os_error_diagnostic("efficiency report artifact unavailable", exc))
    telemetry_overhead_ms = round((time.perf_counter() - overhead_started_at) * 1000, 3)
    report["telemetry_overhead_ms"] = telemetry_overhead_ms
    if telemetry_overhead_ms > TELEMETRY_OVERHEAD_BUDGET_MS and "TELEMETRY_OVERHEAD_EXCEEDED" not in report["diagnostics"]:
        report["diagnostics"].append("TELEMETRY_OVERHEAD_EXCEEDED")
    return report


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
        event_id = metric.execution_id or uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{metric.command}:{metric.start_time}:{metric.end_time}:{metric.exit_code}",
        ).hex
        event = ExternalTelemetryEvent(
            schema_version="1.0",
            source="runtime",
            source_session_id=f"{paths.repo}#{paths.pr_number}",
            event_id=event_id,
            kind="command",
            operation=_safe_runtime_operation(metric.command),
            status="success" if metric.is_success else ("timeout" if metric.exit_code == 124 else "failure"),
            duration_ms=max(0, int(metric.duration * 1000)),
            metadata={"exit_code": metric.exit_code, "is_retry": metric.is_retry},
        )
        events.append(ExternalTelemetryEvent(**{**event.to_dict(), "event_fingerprint": _event_fingerprint(event)}))
    return events


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
