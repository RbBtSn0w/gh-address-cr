from __future__ import annotations

from typing import Any, Iterable, Mapping


def interval_union_ms(spans: Iterable[Mapping[str, Any]]) -> int:
    intervals = sorted(
        (int(span["started_at_ms"]), int(span["ended_at_ms"]))
        for span in spans
        if span.get("started_at_ms") is not None and span.get("ended_at_ms") is not None
    )
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
        if row.get("started_at_ms") is not None and row.get("ended_at_ms") is not None:
            measured = max(measured, int(row["ended_at_ms"]) - int(row["started_at_ms"]))
        resource_time += measured
    return {
        "active_wall_time_ms": interval_union_ms(rows),
        "summed_resource_time_ms": resource_time,
        "measurement_overhead_ms": round(max(0.0, float(measurement_overhead_ms)), 3),
    }
