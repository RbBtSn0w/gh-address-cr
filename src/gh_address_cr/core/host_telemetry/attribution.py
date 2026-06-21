from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.utils import parse_iso_datetime


def session_created_at(repo: str, pr_number: str) -> str | None:
    try:
        payload = json.loads(core_paths.session_file(repo, pr_number).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("created_at") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def lines_in_window(
    lines: list[dict[str, Any]], *, start_iso: str, now_iso: str, timestamp_path: str = "timestamp"
) -> list[dict[str, Any]]:
    start, end = parse_iso_datetime(start_iso), parse_iso_datetime(now_iso)
    if start is None or end is None:
        return []
    kept = []
    for line in lines:
        when = parse_iso_datetime(line.get(timestamp_path))
        if when is not None and start <= when <= end:
            kept.append(line)
    return kept


def distinct_sessions_in_window(
    lines: list[dict[str, Any]],
    *,
    start_iso: str,
    now_iso: str,
    session_id_path: str,
    timestamp_path: str = "timestamp",
) -> set[str]:
    return {
        str(line.get(session_id_path))
        for line in lines_in_window(lines, start_iso=start_iso, now_iso=now_iso, timestamp_path=timestamp_path)
        if line.get(session_id_path)
    }
