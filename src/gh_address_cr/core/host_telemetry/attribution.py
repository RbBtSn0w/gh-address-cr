from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from gh_address_cr.core import paths as core_paths


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def session_created_at(repo: str, pr_number: str) -> str | None:
    try:
        payload = json.loads(core_paths.session_file(repo, pr_number).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("created_at") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def lines_in_window(lines: list[dict[str, Any]], *, start_iso: str, now_iso: str) -> list[dict[str, Any]]:
    start, end = _parse(start_iso), _parse(now_iso)
    if start is None or end is None:
        return []
    kept = []
    for line in lines:
        when = _parse(line.get("timestamp"))
        if when is not None and start <= when <= end:
            kept.append(line)
    return kept


def distinct_sessions_in_window(
    lines: list[dict[str, Any]], *, start_iso: str, now_iso: str, session_id_path: str
) -> set[str]:
    return {
        str(line.get(session_id_path))
        for line in lines_in_window(lines, start_iso=start_iso, now_iso=now_iso)
        if line.get(session_id_path)
    }
