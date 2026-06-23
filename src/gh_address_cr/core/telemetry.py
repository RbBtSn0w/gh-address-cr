from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.command_runner import telemetry_debug_enabled
from gh_address_cr.core.telemetry_session import (
    MAX_DURATION_SECONDS,
    MAX_ERROR_RATE_PERCENT,
    EfficiencyReport,
    ExecutionMetric,
    SessionTelemetry,
    _runtime_events,
)

# Constants re-exported for compatibility
MAX_DURATION_SECONDS = MAX_DURATION_SECONDS
MAX_ERROR_RATE_PERCENT = MAX_ERROR_RATE_PERCENT

# Public API wrappers
def configure_context_safely(repo: str, pr_number: str) -> None:
    """Configure the telemetry session context without ever raising into the caller."""
    try:
        SessionTelemetry.get_instance().configure_context(repo, pr_number)
    except Exception as exc:
        _log_telemetry_failure("context configuration", exc)

def _log_telemetry_failure(action: str, exc: BaseException) -> None:
    """Telemetry is best-effort; never raise into callers, but surface under the debug flag."""
    if telemetry_debug_enabled():
        sys.stderr.write(f"Telemetry {action} failed: {type(exc).__name__}: {exc}\n")

# Compatibility helpers for internal modules (moved logic to sub-modules)
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

def _safe_os_error_diagnostic(prefix: str, exc: OSError) -> str:
    detail = exc.strerror or str(exc)
    return f"{prefix}: {type(exc).__name__}: {detail}"

# Lazy imports to avoid circular dependencies while maintaining re-exports
# These are placed at the end to ensure the module is partially initialized.

def _last_machine_summary_health_issue(paths: core_paths.SessionPaths) -> dict[str, Any] | None:
    # This logic is complex and depends on JSON parsing, keeping it here as a helper
    # used by telemetry_reporting.
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
    except Exception:
        return {
            "reason_code": "TELEMETRY_STORE_UNAVAILABLE",
            "severity": "warning",
            "source": "runtime-summary",
            "retryable": True,
            "detail": "last machine summary unreadable or invalid JSON",
            "next_action": "Repair the runtime summary artifact, then rerun telemetry doctor.",
        }

    if not isinstance(payload, dict):
        return None

    status = str(payload.get("status") or "UNKNOWN")
    observed_reason = str(payload.get("reason_code") or "UNKNOWN_REASON")
    if status == "PASSED" or observed_reason == "PASSED":
        return None

    next_action = str(payload.get("next_action") or "Inspect the last CLI machine summary and rerun the workflow.")
    waiting_on = payload.get("waiting_on")

    return {
        "reason_code": "CLI_WAIT_STATE" if (status.startswith("WAITING") or waiting_on) else "CLI_COMMAND_FAILURE",
        "severity": "info" if (status.startswith("WAITING") or waiting_on) else "warning",
        "source": "runtime-summary",
        "retryable": True,
        "detail": f"CLI summary reported {observed_reason}.",
        "next_action": next_action,
        "metadata": {
            "observed_reason_code": observed_reason,
            "observed_status": status,
            "waiting_on": str(waiting_on) if waiting_on else "",
        },
    }

# Public re-exports
from gh_address_cr.core.telemetry_reporting import (
    build_efficiency_report as build_efficiency_report,
    efficiency_report_markdown as efficiency_report_markdown,
)
from gh_address_cr.core.telemetry_import import (
    TelemetryAdapter as TelemetryAdapter,
    TelemetryParseResult as TelemetryParseResult,
    autodiscovery_miss_import_summary as autodiscovery_miss_import_summary,
    get_adapter as get_adapter,
    hook_unavailable_import_summary as hook_unavailable_import_summary,
    import_external_telemetry as import_external_telemetry,
    input_unavailable_import_summary as input_unavailable_import_summary,
    register_adapter as register_adapter,
    unregister_adapter as unregister_adapter,
)
