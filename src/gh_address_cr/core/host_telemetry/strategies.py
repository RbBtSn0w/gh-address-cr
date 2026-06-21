from __future__ import annotations

from datetime import datetime
from typing import Any

from gh_address_cr.core.host_telemetry.profile import HostProfile


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _blocks(line: dict[str, Any]) -> list[dict[str, Any]]:
    # event_blocks_path is fixed to message.content[] for this strategy.
    message = line.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def paired_correlation_timestamp(
    lines: list[dict[str, Any]],
    profile: HostProfile,
    *,
    session_id: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    f = profile.fields
    tu = f["tool_use"]
    tr = f["tool_result"]
    ts_path = f["timestamp_path"]
    status_map = {str(k): str(v) for k, v in (tr.get("status_map") or {}).items()}

    starts: dict[str, dict[str, Any]] = {}
    results: dict[str, dict[str, Any]] = {}
    sid_path = profile.record.get("session_id_path", "sessionId")

    for line in lines:
        if str(line.get(sid_path) or "") != session_id:
            continue
        when = _parse_ts(line.get(ts_path))
        for block in _blocks(line):
            btype = block.get("type")
            if btype == tu["match"].get("type"):
                starts[str(block.get(tu["id_path"]))] = {
                    "operation": str(block.get(tu["operation_path"]) or "unknown"),
                    "ts": when,
                }
            elif btype == tr["match"].get("type"):
                results[str(block.get(tr["correlation_path"]))] = {
                    "is_error": block.get(tr["status_path"]),
                    "ts": when,
                }

    events: list[dict[str, Any]] = []
    paired = 0
    for tool_id, start in starts.items():
        operation = start["operation"]
        event: dict[str, Any] = {
            "schema_version": "1.0",
            "source": profile.source,
            "source_session_id": session_id,
            "event_id": tool_id,
            "kind": profile.kind_for(operation),
            "operation": operation,
            "status": "unknown",
            "correlation_id": tool_id,
        }
        result = results.get(tool_id)
        if result is not None:
            paired += 1
            key = str(bool(result.get("is_error"))).lower()
            event["status"] = status_map.get(key, "unknown")
            if start["ts"] is not None and result["ts"] is not None:
                event["duration_ms"] = max(0, int((result["ts"] - start["ts"]).total_seconds() * 1000))
        events.append(event)

    stats = {"tool_use_seen": len(starts), "paired": paired}
    return events, stats
