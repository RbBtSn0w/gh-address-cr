from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.telemetry_attribution import ExternalTelemetryEvent, _event_fingerprint
from gh_address_cr.core.telemetry_safety import _safe_runtime_operation

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
        flags: list[str] = []
        if not self.metrics:
            return flags

        def _display_command(command: str) -> str:
            if len(command) > 50:
                return f"{command[:50]}..."
            return command

        for m in self.metrics:
            if m.duration > MAX_DURATION_SECONDS:
                flags.append(
                    f"`{_display_command(m.command)}` took {m.duration:.1f}s (Exceeds {int(MAX_DURATION_SECONDS)}s threshold)."
                )
            if m.exit_code == 124:
                flags.append(f"CRITICAL: `{_display_command(m.command)}` hit execution timeout (hung).")

        total_inv = len(self.metrics)
        successes = sum(1 for m in self.metrics if m.is_success)
        error_rate = ((total_inv - successes) / total_inv) * 100.0
        if error_rate > MAX_ERROR_RATE_PERCENT:
            flags.append(f"Global error rate is {error_rate:.1f}% (Exceeds {MAX_ERROR_RATE_PERCENT}% threshold).")

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

def _runtime_events(paths: core_paths.SessionPaths) -> list[ExternalTelemetryEvent]:
    tracker = SessionTelemetry.get_instance()
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
