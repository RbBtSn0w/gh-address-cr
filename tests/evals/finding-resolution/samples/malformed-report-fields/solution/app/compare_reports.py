"""Compare archived efficiency reports by runtime build.

Reports are read from the gh-address-cr state directory (live sessions and the
archive), so an archived file may be malformed. Output carries runtime labels
and aggregates only, never paths. Reports written before the `runtime` field
existed group under "unknown".
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

FLAG_KINDS = (
    (re.compile(r"^(?P<op>.+?) had \d+ failures"), "error_prone"),
    (re.compile(r"^(?P<op>.+?) exceeded \d+s threshold"), "duration"),
    (re.compile(r"^(?P<op>.+?) latency grew"), "latency_growth"),
)


def flag_kind(flag: str) -> str:
    """A flag's kind and operation, without the counts that vary per session."""
    for pattern, kind in FLAG_KINDS:
        match = pattern.match(flag)
        if match:
            return f"{kind}:{match.group('op')}"
    return "other"


def runtime_label(report: dict[str, Any]) -> str:
    runtime = report.get("runtime")
    if not isinstance(runtime, dict) or not runtime.get("version"):
        return "unknown"
    label = f"{runtime['version']} {runtime.get('origin') or 'unknown'}"
    return f"{label} {runtime['commit']}" if runtime.get("commit") else label


def collect_reports(state_dir: Path) -> list[dict[str, Any]]:
    reports = []
    for path in sorted(state_dir.rglob("efficiency-report.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            reports.append(payload)
    return reports


def _count(value: Any) -> int:
    """A non-negative int count; anything malformed in an archived report counts as zero."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def summarize(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        grouped.setdefault(runtime_label(report), []).append(report)
    summary = {}
    for label, rows in grouped.items():
        rates = [float(row["success_rate"]) for row in rows if isinstance(row.get("success_rate"), (int, float))]
        kinds: Counter[str] = Counter()
        for row in rows:
            flags = row.get("inefficiency_flags")
            if isinstance(flags, list):
                kinds.update({flag_kind(str(flag)) for flag in flags})
        summary[label] = {
            "sessions": len(rows),
            "median_success_rate": statistics.median(rates) if rates else None,
            "needs_action_total": sum(_count(row.get("needs_action_count")) for row in rows),
            "flag_kinds": dict(sorted(kinds.items())),
        }
    return dict(sorted(summary.items()))
