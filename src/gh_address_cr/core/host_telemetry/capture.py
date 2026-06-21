from __future__ import annotations

import json
from pathlib import Path

from gh_address_cr.core.host_telemetry.attribution import lines_in_window
from gh_address_cr.core.host_telemetry.profile import HostProfile
from gh_address_cr.core.host_telemetry.strategies import paired_correlation_timestamp

_MIN_PAIRING_RATIO = 0.5
_STRATEGIES = {"paired-correlation-timestamp": paired_correlation_timestamp}


def _read_lines(path: Path) -> list[dict]:
    out = []
    try:
        for raw in Path(path).read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    except OSError:
        return []
    return out


def capture_agent_jsonl(
    profile: HostProfile,
    *,
    transcript: Path,
    session_id: str,
    start_iso: str,
    now_iso: str,
) -> tuple[str, str]:
    strategy = _STRATEGIES.get(profile.strategy)
    if strategy is None:
        return "", "unavailable"
    all_lines = _read_lines(transcript)
    scoped = lines_in_window(all_lines, start_iso=start_iso, now_iso=now_iso)
    if not scoped:
        return "", "unavailable"
    events, stats = strategy(scoped, profile, session_id=session_id)
    seen = stats.get("tool_use_seen", 0)
    if seen > 0 and (stats.get("paired", 0) / seen) < _MIN_PAIRING_RATIO:
        return "", "degraded"
    if not events:
        return "", "unavailable"
    text = "\n".join(json.dumps(e, sort_keys=True) for e in events)
    return text, "captured"
