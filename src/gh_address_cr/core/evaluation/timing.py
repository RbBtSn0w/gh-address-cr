from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping


def _timestamp_ms(span: Mapping[str, Any], prefix: str) -> int | None:
    numeric = span.get(f"{prefix}_at_ms")
    if numeric is not None:
        return int(numeric)
    value = span.get(f"{prefix}_at")
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{prefix}_at must include a timezone")
    return round(parsed.timestamp() * 1000)


def interval_union_ms(spans: Iterable[Mapping[str, Any]]) -> int:
    intervals = []
    for span in spans:
        start, end = _timestamp_ms(span, "started"), _timestamp_ms(span, "ended")
        if start is not None and end is not None:
            intervals.append((start, end))
    intervals.sort()
    total = 0
    current_start: int | None = None
    current_end: int | None = None
    for start, end in intervals:
        if end < start:
            raise ValueError("span end precedes start")
        if current_end is None or start > current_end:
            if current_start is not None and current_end is not None:
                total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_start is not None and current_end is not None:
        total += current_end - current_start
    return total


def compute_workflow_cost(spans: Iterable[Mapping[str, Any]], *, measurement_overhead_ms: float = 0.0) -> dict[str, Any]:
    rows = list(spans)
    resource_time = 0
    for row in rows:
        measured = max(0, int(row.get("duration_ms") or 0))
        start, end = _timestamp_ms(row, "started"), _timestamp_ms(row, "ended")
        if start is not None and end is not None:
            measured = max(measured, end - start)
        resource_time += measured
    return {
        "active_wall_time_ms": interval_union_ms(rows),
        "summed_resource_time_ms": resource_time,
        "measurement_overhead_ms": round(max(0.0, float(measurement_overhead_ms)), 3),
    }
