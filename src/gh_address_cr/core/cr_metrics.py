from __future__ import annotations

import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.io import write_json_atomic

TERMINAL_EVENT = "thread_resolved"
CLASSIFY_EVENT = "classification_recorded"


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def _empty_report(repo: str, pr_number: str, artifact: Path, diagnostics: list[str], session_id: str = "") -> dict[str, Any]:
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


def build_cr_summary(repo: str, pr_number: str) -> dict[str, Any]:
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

    valid = [(e, _parse_ts(e.get("timestamp"))) for e in events]
    valid = [(e, t) for e, t in valid if t is not None]
    if not valid:
        report = _empty_report(repo, pr_number, artifact, diagnostics)
        _write_artifact(artifact, report)
        return report

    latest_event, _ = max(valid, key=lambda et: et[1])
    latest_session = str(latest_event.get("session_id") or "")
    session_ids = {str(e.get("session_id") or "") for e, _ in valid}
    if len(session_ids) > 1:
        diagnostics.append(f"multiple sessions in ledger: {len(session_ids)}; using latest")

    session_events = [
        (e, t) for e, t in valid if str(e.get("session_id") or "") == latest_session and e.get("item_id")
    ]
    if not session_events:
        report = _empty_report(repo, pr_number, artifact, diagnostics, session_id=latest_session)
        _write_artifact(artifact, report)
        return report

    by_item: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for e, t in session_events:
        by_item.setdefault(str(e["item_id"]), []).append((t, e))

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
