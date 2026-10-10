"""Cross-invocation record of the exit-time telemetry export wait.

The wait happens after the CLI has produced all of its output, so the
invocation that pays it can never include it in its own efficiency report.
Each invocation therefore records its wait here, and the next efficiency report
folds the most recent recorded wait into ``telemetry_overhead_ms``. Telemetry
stays observed evidence: this file never feeds review state or final-gate.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.io import read_json_object, write_json_atomic

SHUTDOWN_WAIT_FILENAME = "telemetry-shutdown-wait.json"
# Every invocation overwrites the record, so a legitimate preceding wait is seconds old.
# An older record means a later invocation did not write one (telemetry disabled, write
# failure), and must not keep inflating telemetry_overhead_ms.
SHUTDOWN_WAIT_MAX_AGE_SECONDS = 300.0
_FUTURE_SKEW_SECONDS = 60.0


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
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    if not _is_recent(payload.get("recorded_at")):
        return None
    return float(value)


def _is_recent(recorded_at: Any) -> bool:
    if not isinstance(recorded_at, str):
        return False
    try:
        recorded = datetime.fromisoformat(recorded_at)
    except ValueError:
        return False
    if recorded.tzinfo is None:
        return False
    age = (datetime.now(timezone.utc) - recorded).total_seconds()
    return -_FUTURE_SKEW_SECONDS <= age <= SHUTDOWN_WAIT_MAX_AGE_SECONDS
