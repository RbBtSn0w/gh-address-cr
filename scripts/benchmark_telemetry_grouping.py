#!/usr/bin/env python3
"""Compare eager ``setdefault`` allocation with explicit grouping checks.

This is an advisory local benchmark. It deliberately keeps timing out of CI;
the JSON output is intended for a PR description or a repeatable local study.
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

from gh_address_cr.core.telemetry_models import ExternalTelemetryEvent

T = TypeVar("T")


def _telemetry_baseline(events: list[ExternalTelemetryEvent]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        row = grouped.setdefault(
            event.operation,
            {"operation": event.operation, "events": 0, "failures": 0, "retries": 0, "timeouts": 0, "sources": set()},
        )
        row["events"] += 1
        row["sources"].add(event.source)
        if event.status in {"failure", "cancelled"}:
            row["failures"] += 1
        if event.status == "timeout":
            row["timeouts"] += 1
        if event.kind == "retry" or (event.metadata or {}).get("is_retry"):
            row["retries"] += 1
    return [
        {
            "operation": row["operation"],
            "events": row["events"],
            "failures": row["failures"],
            "retries": row["retries"],
            "timeouts": row["timeouts"],
            "sources": sorted(row["sources"]),
        }
        for row in grouped.values()
    ]


def _telemetry_candidate(events: list[ExternalTelemetryEvent]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.operation not in grouped:
            grouped[event.operation] = {
                "operation": event.operation,
                "events": 0,
                "failures": 0,
                "retries": 0,
                "timeouts": 0,
                "sources": set(),
            }
        row = grouped[event.operation]
        row["events"] += 1
        row["sources"].add(event.source)
        if event.status in {"failure", "cancelled"}:
            row["failures"] += 1
        if event.status == "timeout":
            row["timeouts"] += 1
        if event.kind == "retry" or (event.metadata or {}).get("is_retry"):
            row["retries"] += 1
    return [
        {
            "operation": row["operation"],
            "events": row["events"],
            "failures": row["failures"],
            "retries": row["retries"],
            "timeouts": row["timeouts"],
            "sources": sorted(row["sources"]),
        }
        for row in grouped.values()
    ]


def _cr_metrics_baseline(events: list[tuple[dict[str, Any], datetime]]) -> dict[str, list[tuple[datetime, dict[str, Any]]]]:
    grouped: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for event, timestamp in events:
        grouped.setdefault(str(event["item_id"]), []).append((timestamp, event))
    return grouped


def _cr_metrics_candidate(events: list[tuple[dict[str, Any], datetime]]) -> dict[str, list[tuple[datetime, dict[str, Any]]]]:
    grouped: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for event, timestamp in events:
        item_id = str(event["item_id"])
        if item_id not in grouped:
            grouped[item_id] = []
        grouped[item_id].append((timestamp, event))
    return grouped


def _telemetry_events(event_count: int, groups: int) -> list[ExternalTelemetryEvent]:
    return [
        ExternalTelemetryEvent(
            schema_version="1.0",
            source=f"source-{index % 3}",
            source_session_id="benchmark",
            event_id=f"event-{index}",
            kind="retry" if index % 11 == 0 else "tool_call",
            operation=f"operation-{index % groups}",
            status="timeout" if index % 17 == 0 else ("failure" if index % 7 == 0 else "success"),
            duration_ms=100,
            metadata={"is_retry": True} if index % 13 == 0 else None,
        )
        for index in range(event_count)
    ]


def _cr_metric_events(event_count: int, groups: int) -> list[tuple[dict[str, Any], datetime]]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        ({"item_id": f"item-{index % groups}", "event_type": "classification_recorded"}, start + timedelta(seconds=index))
        for index in range(event_count)
    ]


def _median_ns(function: Callable[[T], object], payload: T, samples: int, warmups: int) -> int:
    for _ in range(warmups):
        function(payload)
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        measurements = []
        for _ in range(samples):
            started = time.perf_counter_ns()
            function(payload)
            measurements.append(time.perf_counter_ns() - started)
    finally:
        if was_enabled:
            gc.enable()
    return int(statistics.median(measurements))


def _benchmark(
    baseline: Callable[[T], object], candidate: Callable[[T], object], payload: T, samples: int, warmups: int
) -> dict[str, int | float | bool]:
    outputs_equivalent = baseline(payload) == candidate(payload)
    baseline_median_ns = _median_ns(baseline, payload, samples, warmups)
    candidate_median_ns = _median_ns(candidate, payload, samples, warmups)
    improvement_percent = ((baseline_median_ns - candidate_median_ns) / baseline_median_ns) * 100.0
    return {
        "outputs_equivalent": outputs_equivalent,
        "baseline_median_ns": baseline_median_ns,
        "candidate_median_ns": candidate_median_ns,
        "improvement_percent": round(improvement_percent, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=100_000)
    parser.add_argument("--groups", type=int, default=100)
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only.")
    args = parser.parse_args()
    if args.events <= 0 or args.groups <= 0 or args.samples <= 0 or args.warmups < 0:
        parser.error("--events, --groups, and --samples must be positive; --warmups must be non-negative")

    report = {
        "schema_version": 1,
        "runtime": {"implementation": platform.python_implementation(), "python": platform.python_version()},
        "workload": {"events": args.events, "groups": args.groups},
        "samples": args.samples,
        "warmups": args.warmups,
        "benchmarks": {
            "telemetry_reporting": _benchmark(
                _telemetry_baseline,
                _telemetry_candidate,
                _telemetry_events(args.events, args.groups),
                args.samples,
                args.warmups,
            ),
            "cr_metrics": _benchmark(
                _cr_metrics_baseline,
                _cr_metrics_candidate,
                _cr_metric_events(args.events, args.groups),
                args.samples,
                args.warmups,
            ),
        },
    }
    if not all(result["outputs_equivalent"] for result in report["benchmarks"].values()):
        raise AssertionError("candidate output differs from the baseline")
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
