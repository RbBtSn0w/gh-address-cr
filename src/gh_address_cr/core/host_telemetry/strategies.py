from __future__ import annotations

from typing import Any

from gh_address_cr.core.host_telemetry.profile import HostProfile
from gh_address_cr.core.utils import parse_iso_datetime


_DEFAULT_EVENT_BLOCKS_PATH = "message.content[]"


def _blocks(line: dict[str, Any], blocks_path: str = _DEFAULT_EVENT_BLOCKS_PATH) -> list[dict[str, Any]]:
    # Resolve the configured ``event_blocks_path`` (e.g. "message.content[]") so a
    # profile that points the blocks elsewhere is honored instead of silently
    # ignored. The trailing "[]" marks the list segment; any shape mismatch
    # fails open to an empty list rather than raising.
    node: Any = line
    for segment in blocks_path.split("."):
        if not isinstance(node, dict):
            return []
        is_list = segment.endswith("[]")
        node = node.get(segment[:-2] if is_list else segment)
        if is_list:
            if not isinstance(node, list):
                return []
            return [b for b in node if isinstance(b, dict)]
    return []


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
    blocks_path = str(f.get("event_blocks_path") or _DEFAULT_EVENT_BLOCKS_PATH)
    status_map = {str(k): str(v) for k, v in (tr.get("status_map") or {}).items()}

    starts: dict[str, dict[str, Any]] = {}
    results: dict[str, dict[str, Any]] = {}
    sid_path = profile.record.get("session_id_path", "sessionId")

    for line in lines:
        if str(line.get(sid_path) or "") != session_id:
            continue
        when = parse_iso_datetime(line.get(ts_path))
        for block in _blocks(line, blocks_path):
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
            "duration_ms": 0,
            "correlation_id": tool_id,
        }
        result = results.get(tool_id)
        if result is not None:
            paired += 1
            is_error = result.get("is_error")
            if is_error is None:
                event["status"] = "unknown"
            else:
                key = str(bool(is_error)).lower()
                event["status"] = status_map.get(key, "unknown")
            if start["ts"] is not None and result["ts"] is not None:
                event["duration_ms"] = max(0, int((result["ts"] - start["ts"]).total_seconds() * 1000))
        events.append(event)

    stats = {"tool_use_seen": len(starts), "paired": paired}
    return events, stats
