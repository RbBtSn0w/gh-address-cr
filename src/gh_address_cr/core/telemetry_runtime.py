from __future__ import annotations

import json
import math
import os
import re
import uuid
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, ClassVar

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


NEEDS_ACTION_EXIT_CODE = 5
# Reason codes that mean "the command worked and the PR still needs work". Exit 5
# is shared with errors and rejected agent input, so only these are needs-action
# (Spec 039 R1, issue #307); anything else non-zero stays a failure.
NEEDS_ACTION_REASON_CODES = frozenset(
    {
        "WAITING_FOR_SIMPLE_ADDRESS",
        "BLOCKING_ITEMS_REMAIN",
        "WAITING_FOR_FIX",
        "AUTO_SIMPLE_NOT_ELIGIBLE",
        "FINAL_GATE_UNRESOLVED_REMOTE_THREADS",
        "FINAL_GATE_MISSING_REPLY_EVIDENCE",
        "FINAL_GATE_PENDING_CURRENT_LOGIN_REVIEW",
        "FINAL_GATE_BLOCKING_GITHUB_ITEMS",
        "FINAL_GATE_BLOCKING_LOCAL_ITEMS",
        "FINAL_GATE_MISSING_VALIDATION_EVIDENCE",
        "FINAL_GATE_PR_CHECKS_NOT_GREEN",
        "FINAL_GATE_REQUIRED_CHECKS_MISSING",
        "FINAL_GATE_LOGIC_VALIDATION_BLOCKING",
        "FINAL_GATE_STALE_REVISION_EVIDENCE",
        "FINAL_GATE_UNBOUND_REVISION_EVIDENCE",
    }
)

_COMMAND_REASON_CODE: ContextVar[str | None] = ContextVar("gh_address_cr_command_reason_code", default=None)


def classify_command_outcome(exit_code: int, reason_code: str | None) -> str:
    if exit_code == 0:
        return "success"
    if exit_code == 124:
        return "timeout"
    if exit_code == NEEDS_ACTION_EXIT_CODE and reason_code in NEEDS_ACTION_REASON_CODES:
        return "needs_action"
    return "failure"


_REASON_CODE_SPAN_ATTRIBUTE = "gh_address_cr.command.reason_code"
# Reason codes are a fixed public enum; anything else is not safe to export as a span attribute.
_REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def note_command_reason_code(reason_code: str | None) -> None:
    """Record the reason code the current command emitted, for its outcome metric and the current span.

    Failure output helpers call this from the command handler, where the current span is the
    CLI root span.
    """
    _COMMAND_REASON_CODE.set(reason_code)
    if reason_code and _REASON_CODE_PATTERN.fullmatch(reason_code):
        try:
            from gh_address_cr.otel_tracing import set_current_span_attributes

            set_current_span_attributes({_REASON_CODE_SPAN_ATTRIBUTE: reason_code})
        except Exception as exc:
            _log_telemetry_failure("reason code span attribute", exc)


def reset_command_reason_code() -> None:
    _COMMAND_REASON_CODE.set(None)


def command_reason_code() -> str | None:
    return _COMMAND_REASON_CODE.get()


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
        self._metrics: list[ExecutionMetric] = []
        self.telemetry_file: Path | None = None
        self._loaded_files: set[Path] = set()
        self._pending_files: list[Path] = []
        self.paths: core_paths.SessionPaths | None = None

    @property
    def metrics(self) -> list[ExecutionMetric]:
        """All metrics for the configured session, loading persisted history on first use.

        Binding a PR happens on every session load and transaction, while the
        history is only needed to build a report; loading it lazily keeps the
        per-command cost from growing with the session's telemetry file.
        """
        while self._pending_files:
            self._load_persisted_metrics(self._pending_files.pop(0))
        return self._metrics

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
        self._metrics.clear()
        self._loaded_files.clear()
        self._pending_files.clear()
        self.paths = core_paths.SessionPaths(repo, pr_number)
        path = self.paths.workspace_dir / "telemetry.jsonl"
        self.configure_file(path)

    def configure_file(self, path: Path) -> None:
        self.telemetry_file = path
        if path not in self._loaded_files and path not in self._pending_files:
            self._pending_files.append(path)

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
                    except ValueError:
                        continue
                    metric = self._metric_from_payload(payload)
                    if metric is not None:
                        loaded_metrics.append(metric)
            self._metrics.extend(loaded_metrics)
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
                persistence_ms=_optional_float(payload.get("persistence_ms")),
                lock_wait_ms=_optional_float(payload.get("lock_wait_ms")),
                outcome=_optional_outcome(payload.get("outcome")),
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
        persistence_ms: float | None = None,
        lock_wait_ms: float | None = None,
        outcome: str | None = None,
    ) -> None:
        is_retry = False
        last_metric = self._last_metric()
        # Rerunning `address` after a needs-action block is the documented loop, not a retry.
        if last_metric is not None and last_metric.command == command and last_metric.counts_as_failure:
            is_retry = True

        metric = ExecutionMetric(
            command=command,
            start_time=start_time,
            end_time=end_time,
            exit_code=exit_code,
            is_retry=is_retry,
            pid=pid if pid is not None else os.getpid(),
            execution_id=execution_id if execution_id is not None else uuid.uuid4().hex,
            persistence_ms=persistence_ms,
            lock_wait_ms=lock_wait_ms,
            outcome=outcome,
        )
        persisted = self._persist_metric(metric)
        # With history not yet loaded, a persisted line arrives with it later; keep the
        # metric in memory now only when it was not persisted, so it is never lost or doubled.
        if not self._pending_files or not persisted:
            self._metrics.append(metric)

    def _last_metric(self) -> ExecutionMetric | None:
        if not self._pending_files:
            return self._metrics[-1] if self._metrics else None
        path = self._pending_files[-1]
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - 8192))
                tail = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return None
        for line in reversed(tail.splitlines()):
            if not line.strip():
                continue
            try:
                return self._metric_from_payload(json.loads(line))
            except ValueError:
                continue
        return None

    def _persist_metric(self, metric: ExecutionMetric) -> bool:
        if self.telemetry_file is None:
            return False
        try:
            self.telemetry_file.parent.mkdir(parents=True, exist_ok=True)
            with self.telemetry_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(metric.to_dict(), sort_keys=True) + "\n")
        except OSError:
            return False
        return True

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


def _optional_outcome(value: Any) -> str | None:
    return value if value in {"success", "needs_action", "timeout", "failure"} else None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None
