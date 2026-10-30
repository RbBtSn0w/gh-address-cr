"""Cross-invocation record of the exit-time telemetry export wait.

The wait happens after the CLI has produced all of its output, so the
invocation that pays it can never include it in its own efficiency report.
Each invocation therefore records its wait here, and the next efficiency report
folds the most recent recorded wait into ``telemetry_overhead_ms``. Telemetry
stays observed evidence: this file never feeds review state or final-gate.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHUTDOWN_WAIT_FILENAME = "telemetry-shutdown-wait.json"


def shutdown_wait_file(state_dir: Path) -> Path:
    return state_dir / SHUTDOWN_WAIT_FILENAME


def record_shutdown_wait(state_dir: Path, wait_ms: float, *, timed_out: bool) -> None:
    """Best-effort record of this invocation's exit wait. Never raises."""
    try:
        path = shutdown_wait_file(state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "wait_ms": round(wait_ms, 3),
            "timed_out": timed_out,
            "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        return


def read_last_shutdown_wait_ms(state_dir: Path) -> float | None:
    """Return the most recent recorded exit wait, or None when unavailable."""
    try:
        payload = json.loads(shutdown_wait_file(state_dir).read_text(encoding="utf-8"))
        value = payload.get("wait_ms")
    except Exception:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)
