from __future__ import annotations

import json
import math
import os
import uuid
from contextvars import ContextVar, Token
from pathlib import Path
from typing import ClassVar

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.command_runner import telemetry_debug_enabled
from gh_address_cr.core.telemetry_models import (
    MAX_DURATION_SECONDS,
    MAX_ERROR_RATE_PERCENT,
    EfficiencyReport,
    ExecutionMetric,
)


def _log_telemetry_failure(action: str, exc: BaseException) -> None:
    """Telemetry is best-effort; never raise into callers, but surface under the debug flag."""
    if telemetry_debug_enabled():
        import sys

        sys.stderr.write(f"Telemetry {action} failed: {type(exc).__name__}: {exc}\n")


_ACTIVE_SESSION_TELEMETRY: ContextVar["SessionTelemetry | None"] = ContextVar(
    "gh_address_cr_active_session_telemetry",
    default=None,
)


def configure_context_safely(repo: str, pr_number: str) -> SessionTelemetry | None:
    """Configure the telemetry session context without ever raising into the caller."""
    try:
        tracker = SessionTelemetry()
        tracker.configure_context(repo, str(pr_number))
        tracker.activate()
        return tracker
    except Exception as exc:  # intentionally broad: telemetry must not break core flows
        _log_telemetry_failure("context configuration", exc)
        return None


class SessionTelemetry:
    _instance: ClassVar[SessionTelemetry | None] = None

    def __init__(self) -> None:
        self.metrics: list[ExecutionMetric] = []
        self.telemetry_file: Path | None = None
        self._loaded_files: set[Path] = set()
        self.paths: core_paths.SessionPaths | None = None

    @classmethod
    def get_instance(cls) -> SessionTelemetry:
        current = _ACTIVE_SESSION_TELEMETRY.get()
        if current is not None:
            return current
        if cls._instance is None:
            cls._instance = SessionTelemetry()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        _ACTIVE_SESSION_TELEMETRY.set(None)
        cls._instance = None

    def activate(self) -> Token[SessionTelemetry | None]:
        return _ACTIVE_SESSION_TELEMETRY.set(self)

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

        for metric in self.metrics:
            if metric.duration > MAX_DURATION_SECONDS:
                flags.append(
                    f"`{_display_command(metric.command)}` took {metric.duration:.1f}s (Exceeds {int(MAX_DURATION_SECONDS)}s threshold)."
                )
            if metric.exit_code == 124:
                flags.append(f"CRITICAL: `{_display_command(metric.command)}` hit execution timeout (hung).")

        total_invocations = len(self.metrics)
        successes = sum(1 for metric in self.metrics if metric.is_success)
        error_rate = ((total_invocations - successes) / total_invocations) * 100.0
        if error_rate > MAX_ERROR_RATE_PERCENT:
            flags.append(f"Global error rate is {error_rate:.1f}% (Exceeds {MAX_ERROR_RATE_PERCENT}% threshold).")

        consecutive_retries: dict[str, int] = {}
        current_command: str | None = None
        current_retry_count = 0
        for metric in self.metrics:
            if metric.command != current_command:
                if current_command is not None:
                    consecutive_retries[current_command] = max(
                        consecutive_retries.get(current_command, 0),
                        current_retry_count,
                    )
                current_command = metric.command
                current_retry_count = 0
            if metric.is_retry:
                current_retry_count += 1

        if current_command is not None:
            consecutive_retries[current_command] = max(
                consecutive_retries.get(current_command, 0),
                current_retry_count,
            )

        for command, count in consecutive_retries.items():
            if count >= 1:
                retry_word = "retry" if count == 1 else "retries"
                flags.append(
                    f"`{_display_command(command)}` ran {count + 1} times consecutively with {count} {retry_word} (High Retry Rate)."
                )

        return flags

    def get_report(self) -> EfficiencyReport:
        total_invocations = len(self.metrics)
        if total_invocations == 0:
            return EfficiencyReport(0, 0.0, 0.0, [], [])

        total_duration = sum(metric.duration for metric in self.metrics)
        successes = sum(1 for metric in self.metrics if metric.is_success)
        success_rate = (successes / total_invocations) * 100.0

        return EfficiencyReport(
            total_invocations=total_invocations,
            total_duration=total_duration,
            success_rate=success_rate,
            flagged_inefficiencies=self.evaluate_efficiency(),
            metrics=list(self.metrics),
        )

    def get_summary_string(self) -> str | None:
        if not self.metrics:
            return None

        report = self.get_report()
        summary = f"{report.total_invocations} tools invoked ({report.success_rate:.0f}% success). Total tool duration: {report.total_duration:.1f}s."
        if report.flagged_inefficiencies:
            summary += "\n> ⚠️ **Inefficiencies Detected**:\n"
            summary += "\n".join(f"> - {flag}" for flag in report.flagged_inefficiencies)
        return summary
