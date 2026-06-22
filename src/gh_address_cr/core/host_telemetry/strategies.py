from __future__ import annotations

from typing import Any

from gh_address_cr.core.host_telemetry.attribution import value_at_path
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


def record_pair_timestamp(
    lines: list[dict[str, Any]],
    profile: HostProfile,
    *,
    session_id: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    f = profile.fields
    ts_path = str(f.get("timestamp_path") or "timestamp")
    event_type_path = str(f.get("event_type_path") or "payload.type")
    correlation_id_path = str(f.get("correlation_id_path") or "payload.call_id")
    operation_path = str(f.get("operation_path") or "payload.name")
    session_id_path = str(profile.record.get("session_id_path") or "payload.id")
    session_record_match = f.get("session_record_match") or {"type": "session_meta"}
    event_record_match = f.get("event_record_match") or {"type": "response_item"}
    start_match = f.get("start_match") or {"payload.type": "function_call"}
    end_match = f.get("end_match") or {"payload.type": "function_call_output"}

    session_meta_seen = False
    starts: dict[str, dict[str, Any]] = {}
    results: dict[str, dict[str, Any]] = {}
    for line in lines:
        if _matches(line, session_record_match):
            meta_session_id = value_at_path(line, session_id_path)
            if meta_session_id and str(meta_session_id) != session_id:
                return [], {"call_started": 0, "paired": 0}
            session_meta_seen = True
            continue
        if not _matches(line, event_record_match):
            continue
        event_type = value_at_path(line, event_type_path)
        call_id = value_at_path(line, correlation_id_path)
        if not call_id:
            continue
        call_id = str(call_id)
        when = parse_iso_datetime(value_at_path(line, ts_path))
        if _matches(line, start_match):
            starts[call_id] = {
                "operation": str(value_at_path(line, operation_path) or event_type or "tool_call"),
                "ts": when,
            }
        elif _matches(line, end_match):
            results[call_id] = {"ts": when}

    if not session_meta_seen:
        return [], {"call_started": 0, "paired": 0}

    events: list[dict[str, Any]] = []
    paired = 0
    for call_id, start in starts.items():
        result = results.get(call_id)
        duration_ms = 0
        status = "unknown"
        if result is not None:
            paired += 1
            if start["ts"] is not None and result["ts"] is not None:
                duration_ms = max(0, int((result["ts"] - start["ts"]).total_seconds() * 1000))
        events.append(
            {
                "schema_version": "1.0",
                "source": profile.source,
                "source_session_id": session_id,
                "event_id": call_id,
                "kind": profile.kind_for(start["operation"]),
                "operation": start["operation"],
                "status": status,
                "duration_ms": duration_ms,
                "correlation_id": call_id,
            }
        )

    return events, {"call_started": len(starts), "paired": paired}


def _matches(line: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(value_at_path(line, str(path)) == value for path, value in expected.items())
