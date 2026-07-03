from __future__ import annotations

import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.utils import parse_iso_datetime

TERMINAL_EVENT = "thread_resolved"
CLASSIFY_EVENT = "classification_recorded"


def _read_ledger(path: Path) -> tuple[list[dict[str, Any]], bool, list[str]]:
    """Return (events, unreadable, diagnostics). Missing file is empty (not unreadable)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], False, []
    except OSError:
        return [], True, []
    events: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for index, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            diagnostics.append(f"evidence ledger line {index}: invalid JSON")
            continue
        if not isinstance(obj, dict):
            diagnostics.append(f"evidence ledger line {index}: not an object")
            continue
        events.append(obj)
    return events, False, diagnostics


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def _empty_report(
    repo: str, pr_number: str, artifact: Path, diagnostics: list[str], session_id: str = ""
) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "reason_code": "CR_LEDGER_EMPTY",
        "repo": repo,
        "pr_number": str(pr_number),
        "session_id": session_id,
        "cr_count_total": 0,
        "cr_count_completed": 0,
        "cr_count_incomplete": 0,
        "span_ms": {"median": None, "p90": None, "max": None, "min": None},
        "run_wall_clock_ms": 0,
        "active_cr_time_ms": 0,
        "compactness_ratio": None,
        "classification_mix": {},
        "incomplete_crs": [],
        "per_cr": [],
        "report_artifact": str(artifact),
        "diagnostics": diagnostics,
    }


def _write_artifact(artifact: Path, report: dict[str, Any]) -> None:
    try:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(artifact, report)
    except OSError as exc:
        report["diagnostics"].append(f"cr-metrics artifact unavailable: {type(exc).__name__}")


def build_cr_summary(repo: str, pr_number: str) -> dict[str, Any]:  # noqa: C901
    path = core_paths.evidence_ledger_file(repo, pr_number)
    artifact = core_paths.workspace_dir(repo, pr_number) / "cr-metrics.json"
    events, unreadable, diagnostics = _read_ledger(path)
    if unreadable:
        return {
            "status": "FAILED",
            "reason_code": "CR_SUMMARY_UNAVAILABLE",
            "repo": repo,
            "pr_number": str(pr_number),
            "diagnostics": ["evidence ledger unreadable"],
            "report_artifact": str(artifact),
        }

    parsed = [(e, parse_iso_datetime(e.get("timestamp"))) for e in events]
    dropped_timestamp = sum(1 for _, t in parsed if t is None)
    if dropped_timestamp:
        diagnostics.append(f"skipped {dropped_timestamp} event(s) with missing or unparseable timestamp")
    valid = [(e, t) for e, t in parsed if t is not None]
    if not valid:
        report = _empty_report(repo, pr_number, artifact, diagnostics)
        _write_artifact(artifact, report)
        return report

    latest_event, _ = max(valid, key=lambda et: et[1])
    latest_session = str(latest_event.get("session_id") or "")
    session_ids = {str(e.get("session_id") or "") for e, _ in valid}
    if len(session_ids) > 1:
        diagnostics.append(f"multiple sessions in ledger: {len(session_ids)}; using latest")

    in_session = [(e, t) for e, t in valid if str(e.get("session_id") or "") == latest_session]
    dropped_item_id = sum(1 for e, _ in in_session if not e.get("item_id"))
    if dropped_item_id:
        diagnostics.append(f"skipped {dropped_item_id} event(s) with missing item_id")
    session_events = [(e, t) for e, t in in_session if e.get("item_id")]
    if not session_events:
        report = _empty_report(repo, pr_number, artifact, diagnostics, session_id=latest_session)
        _write_artifact(artifact, report)
        return report

    by_item: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for e, t in session_events:
        item_id = str(e["item_id"])
        if item_id not in by_item:
            by_item[item_id] = []
        by_item[item_id].append((t, e))

    per_cr: list[dict[str, Any]] = []
    completed_spans: list[int] = []
    incomplete: list[dict[str, Any]] = []
    classification_mix: dict[str, int] = {}
    all_ts = [t for _, t in session_events]

    for item_id, entries in by_item.items():
        entries.sort(key=lambda te: te[0])
        start = entries[0][0]
        classification: str | None = None
        for _, e in entries:
            if e.get("event_type") == CLASSIFY_EVENT:
                value = (e.get("payload") or {}).get("classification")
                if isinstance(value, str):
                    classification = value
        if classification:
            classification_mix[classification] = classification_mix.get(classification, 0) + 1
        terminal = [t for t, e in entries if e.get("event_type") == TERMINAL_EVENT]
        if terminal:
            span = max(0, int((max(terminal) - start).total_seconds() * 1000))
            completed_spans.append(span)
            per_cr.append({"item_id": item_id, "span_ms": span, "completed": True, "classification": classification})
        else:
            incomplete.append({"item_id": item_id, "last_event_type": entries[-1][1].get("event_type")})
            per_cr.append({"item_id": item_id, "span_ms": None, "completed": False, "classification": classification})

    span_ms: dict[str, Any]
    if completed_spans:
        span_ms = {
            "median": int(statistics.median(completed_spans)),
            "p90": _percentile(completed_spans, 0.9),
            "max": max(completed_spans),
            "min": min(completed_spans),
        }
    else:
        span_ms = {"median": None, "p90": None, "max": None, "min": None}

    wall = int((max(all_ts) - min(all_ts)).total_seconds() * 1000)
    active = sum(completed_spans)
    compactness = round(active / wall, 2) if wall > 0 else None
    per_cr.sort(key=lambda row: (row["span_ms"] is None, -(row["span_ms"] or 0)))

    report = {
        "status": "SUCCESS",
        "reason_code": "CR_SUMMARY_READY",
        "repo": repo,
        "pr_number": str(pr_number),
        "session_id": latest_session,
        "cr_count_total": len(by_item),
        "cr_count_completed": len(completed_spans),
        "cr_count_incomplete": len(incomplete),
        "span_ms": span_ms,
        "run_wall_clock_ms": wall,
        "active_cr_time_ms": active,
        "compactness_ratio": compactness,
        "classification_mix": classification_mix,
        "incomplete_crs": incomplete,
        "per_cr": per_cr,
        "report_artifact": str(artifact),
        "diagnostics": diagnostics,
    }
    _write_artifact(artifact, report)
    return report


def _ms(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value / 1000:.1f}s"


def cr_summary_markdown(report: dict[str, Any]) -> str:
    span = report.get("span_ms") or {}
    lines = [
        "## CR Processing Summary (latest session)",
        f"- CRs: {report.get('cr_count_completed', 0)} completed, {report.get('cr_count_incomplete', 0)} incomplete",
        f"- per-CR span: median {_ms(span.get('median'))} | p90 {_ms(span.get('p90'))} | max {_ms(span.get('max'))}",
        f"- run wall-clock: {_ms(report.get('run_wall_clock_ms'))} | active CR time: {_ms(report.get('active_cr_time_ms'))} | compactness: {report.get('compactness_ratio')}",
    ]
    mix = report.get("classification_mix") or {}
    if mix:
        lines.append("- classification: " + ", ".join(f"{k} {v}" for k, v in sorted(mix.items())))
    completed = [r for r in report.get("per_cr", []) if r.get("completed")]
    if completed:
        lines.extend(["", "### Slowest CRs"])
        for row in completed[:5]:
            lines.append(f"- {row['item_id']} : {_ms(row['span_ms'])} ({row.get('classification') or 'n/a'})")
    incomplete = report.get("incomplete_crs") or []
    lines.extend(["", "### Incomplete CRs"])
    if incomplete:
        for row in incomplete:
            lines.append(f"- {row['item_id']} : {row['last_event_type']}")
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"
