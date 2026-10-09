"""Cross-invocation record of the exit-time telemetry export wait.

The wait happens after the CLI has produced all of its output, so the
invocation that pays it can never include it in its own efficiency report.
Each invocation therefore records its wait here, and the next efficiency report
folds the most recent recorded wait into ``telemetry_overhead_ms``. Telemetry
stays observed evidence: this file never feeds review state or final-gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.io import read_json_object, write_json_atomic

SHUTDOWN_WAIT_FILENAME = "telemetry-shutdown-wait.json"


def shutdown_wait_file() -> Path:
    return core_paths.state_dir() / SHUTDOWN_WAIT_FILENAME


def record_shutdown_wait(wait_ms: float, *, timed_out: bool) -> None:
    """Best-effort record of this invocation's exit wait. Never raises."""
    try:
        path = shutdown_wait_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "wait_ms": round(wait_ms, 3),
            "timed_out": timed_out,
            "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        write_json_atomic(path, payload)
    except Exception:
        return


def read_last_shutdown_wait_ms() -> float | None:
    """Return the most recent recorded exit wait, or None when unavailable."""
    try:
        payload = read_json_object(shutdown_wait_file())
        value = payload.get("wait_ms")
    except Exception:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)
