from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from gh_address_cr.core import paths as core_paths
from gh_address_cr.core.io import write_json_atomic
from gh_address_cr.core.utils import parse_iso_datetime

TERMINAL_EVENT = "thread_resolved"
CLASSIFY_EVENT = "classification_recorded"
LIFECYCLE_SCHEMA_VERSION = "cr-lifecycle.v1"


def _distribution(values: list[int], *, total: int) -> dict[str, int | None]:
    if not values:
        return {
            "median": None,
            "p90": None,
            "max": None,
            "min": None,
            "sample_count": 0,
            "excluded": total,
        }
    return {
        "median": _median(values),
        "p90": _percentile(values, 0.9),
        "max": max(values),
        "min": min(values),
        "sample_count": len(values),
        "excluded": max(0, total - len(values)),
    }


def _duration_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None or end < start:
        return None
    return int((end - start).total_seconds() * 1000)


def _prepare_lifecycle_events(
    events: list[dict[str, Any]],
) -> tuple[str, dict[str, list[tuple[datetime, dict[str, Any]]]], list[str]]:
    unique_events: list[dict[str, Any]] = []
    seen_records: dict[str, str] = {}
    conflicting_duplicates = 0
    for event in events:
        record_id = str(event.get("record_id") or "")
        if record_id:
            encoded = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            if record_id in seen_records:
                conflicting_duplicates += int(seen_records[record_id] != encoded)
                continue
            seen_records[record_id] = encoded
        unique_events.append(event)

    parsed = [(event, parse_iso_datetime(event.get("timestamp"))) for event in unique_events]
    dropped_timestamp = sum(1 for _, timestamp in parsed if timestamp is None)
    diagnostics = (
        [f"skipped {dropped_timestamp} event(s) with missing or unparseable timestamp"]
        if dropped_timestamp
        else []
    )
    if conflicting_duplicates:
        diagnostics.append(f"conflicting duplicate evidence record(s): {conflicting_duplicates}")

    valid = [(event, timestamp) for event, timestamp in parsed if timestamp is not None and event.get("item_id")]
    session_id = ""
    if valid:
        latest_event, _ = max(valid, key=lambda row: row[1])
        session_id = str(latest_event.get("session_id") or "")
        valid = [(event, timestamp) for event, timestamp in valid if str(event.get("session_id") or "") == session_id]
    by_item: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for event, timestamp in valid:
        by_item.setdefault(str(event["item_id"]), []).append((timestamp, event))
    return session_id, by_item, diagnostics


def _verified_timestamp(
    item_kind: str,
    entries: list[tuple[datetime, dict[str, Any]]],
    accepted: list[tuple[datetime, dict[str, Any]]],
) -> datetime | None:
    if item_kind == "github_thread":
        terminal = [timestamp for timestamp, event in entries if event.get("event_type") == "response_published"]
    elif item_kind == "local_finding":
        last_rejection = max(
            (timestamp for timestamp, event in entries if event.get("event_type") == "verification_rejected"),
            default=None,
        )
        terminal = [
            timestamp
            for timestamp, event in accepted
            if event.get("role") == "verifier" and (last_rejection is None or timestamp > last_rejection)
        ]
    else:
        terminal = []
    return min(terminal) if terminal else None


def _project_lifecycle_item(
    item_id: str,
    entries: list[tuple[datetime, dict[str, Any]]],
) -> tuple[dict[str, Any], datetime, datetime | None]:
    observations = [(timestamp, event) for timestamp, event in entries if event.get("event_type") == "finding_observed"]
    first_observation = min(observations, key=lambda row: row[0]) if observations else None
    observed_at = first_observation[0] if first_observation else min(timestamp for timestamp, _ in entries)
    provenance = "finding_observed" if observations else "first_evidence"
    observed_item_kinds = {
        str((event.get("payload") or {}).get("item_kind") or "")
        for _, event in observations
        if (event.get("payload") or {}).get("item_kind")
    }
    item_kind_ambiguous = len(observed_item_kinds) > 1
    item_kind = next(iter(observed_item_kinds)) if len(observed_item_kinds) == 1 else ""
    accepted = [(timestamp, event) for timestamp, event in entries if event.get("event_type") == "response_accepted"]
    address_acceptances = [(timestamp, event) for timestamp, event in accepted if event.get("role") != "verifier"]
    addressed_at = min((timestamp for timestamp, _ in address_acceptances), default=None)
    verified_at = _verified_timestamp(item_kind, entries, accepted)
    counts = {
        "address_attempts": len(address_acceptances),
        "response_rejections": sum(1 for _, event in entries if event.get("event_type") == "response_rejected"),
        "verification_rejections": sum(1 for _, event in entries if event.get("event_type") == "verification_rejected"),
        "publish_blocked": sum(1 for _, event in entries if event.get("event_type") == "publish_blocked"),
    }
    exclusions: list[str] = []
    if provenance != "finding_observed":
        exclusions.append("observation_inferred")
    if item_kind_ambiguous:
        exclusions.append("item_kind_ambiguous")
    elif not item_kind:
        exclusions.append("item_kind_unknown")
    if addressed_at is None:
        exclusions.append("addressed_at_missing")
    if verified_at is None:
        exclusions.append("verified_at_missing")
    durations = {
        "observed_to_addressed": _duration_ms(observed_at, addressed_at),
        "addressed_to_verified": _duration_ms(addressed_at, verified_at),
        "observed_to_verified": _duration_ms(observed_at, verified_at),
    }
    if addressed_at is not None and durations["observed_to_addressed"] is None:
        exclusions.append("addressed_before_observed")
    if verified_at is not None and durations["observed_to_verified"] is None:
        exclusions.append("verified_before_observed")
    if addressed_at is not None and verified_at is not None and durations["addressed_to_verified"] is None:
        exclusions.append("verified_before_addressed")
    first_pass = None
    if verified_at is not None:
        first_pass = counts["address_attempts"] == 1 and all(
            counts[name] == 0 for name in ("response_rejections", "verification_rejections", "publish_blocked")
        )
    return (
        {
            "item_id": item_id,
            "item_kind": item_kind or None,
            "observation_provenance": provenance,
            "timestamps": {
                "observed_at": observed_at.isoformat(),
                "addressed_at": addressed_at.isoformat() if addressed_at else None,
                "verified_at": verified_at.isoformat() if verified_at else None,
            },
            "durations_ms": durations,
            "counts": counts,
            "first_pass_verified": first_pass,
            "eligible": not exclusions,
            "exclusion_reasons": exclusions,
        },
        observed_at,
        verified_at,
    )


def _lifecycle_aggregates(items: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in items if item["eligible"]]
    verified = [item for item in items if item["timestamps"]["verified_at"] is not None]
    total_items = len(items)

    def durations(name: str) -> list[int]:
        return [int(item["durations_ms"][name]) for item in eligible]

    def friction(name: str) -> dict[str, int | float | None]:
        count = sum(int(item["counts"][name]) for item in items)
        denominator = len(verified)
        return {
            "count": count,
            "denominator": denominator,
            "per_verified_item": round(count / denominator, 4) if denominator else None,
            "excluded": total_items - denominator,
        }

    stage_candidates = [
        {
            "item_id": item["item_id"],
            "stage": stage,
            "duration_ms": int(item["durations_ms"][stage]),
        }
        for item in eligible
        for stage in ("observed_to_addressed", "addressed_to_verified")
    ]
    slowest_stage = (
        min(stage_candidates, key=lambda row: (-row["duration_ms"], row["item_id"], row["stage"]))
        if stage_candidates
        else None
    )
    first_pass_numerator = sum(item["first_pass_verified"] is True for item in verified)
    return {
        "verified_items": len(verified),
        "eligible_items": len(eligible),
        "excluded_items": total_items - len(eligible),
        "observed_to_addressed_ms": _distribution(durations("observed_to_addressed"), total=total_items),
        "addressed_to_verified_ms": _distribution(durations("addressed_to_verified"), total=total_items),
        "observed_to_verified_ms": _distribution(durations("observed_to_verified"), total=total_items),
        "slowest_stage": slowest_stage,
        "first_pass_verified_rate": {
            "numerator": first_pass_numerator,
            "denominator": len(verified),
            "rate": round(first_pass_numerator / len(verified), 4) if verified else None,
            "excluded": total_items - len(verified),
        },
        "friction": {
            name: friction(name)
            for name in ("address_attempts", "response_rejections", "verification_rejections", "publish_blocked")
        },
    }


def project_cr_lifecycle(
    events: list[dict[str, Any]],
    *,
    repo: str,
    pr_number: str,
    gate_completed_at: str | None = None,
) -> dict[str, Any]:
    """Project one session's ordered evidence into advisory lifecycle metrics."""
    session_id, by_item, diagnostics = _prepare_lifecycle_events(events)
    items: list[dict[str, Any]] = []
    exact_observed: list[datetime] = []
    verified_times: list[datetime] = []
    for item_id, entries in by_item.items():
        item, observed_at, verified_at = _project_lifecycle_item(item_id, entries)
        if item["eligible"]:
            exact_observed.append(observed_at)
            assert verified_at is not None
            verified_times.append(verified_at)
        items.append(item)

    gate_time = parse_iso_datetime(gate_completed_at) if gate_completed_at else None
    first_to_gate = _duration_ms(min(exact_observed), gate_time) if exact_observed else None
    verified_to_gate = _duration_ms(max(verified_times), gate_time) if verified_times else None
    aggregates = _lifecycle_aggregates(items)
    completeness = (
        "empty"
        if not items
        else ("complete" if aggregates["excluded_items"] == 0 else "partial")
    )
    return {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "completeness": completeness,
        "status": "SUCCESS",
        "reason_code": "CR_LIFECYCLE_READY" if items else "CR_LEDGER_EMPTY",
        "repo": repo,
        "pr_number": str(pr_number),
        "session_id": session_id,
        "items": items,
        "aggregates": aggregates,
        "pr_durations_ms": {
            "first_observed_to_merge_ready": first_to_gate,
            "last_verified_to_merge_ready": verified_to_gate,
        },
        "diagnostics": diagnostics,
    }


def _scan_ledger(path: Path) -> tuple[datetime | None, str, set[str], int, list[str]]:
    diagnostics: list[str] = []
    latest_timestamp: datetime | None = None
    latest_session = ""
    session_ids: set[str] = set()
    unparseable_timestamps = 0
    with path.open(encoding="utf-8") as handle:
        for index, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
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
            timestamp = parse_iso_datetime(obj.get("timestamp"))
            if timestamp is None:
                unparseable_timestamps += 1
                continue
            session_id = str(obj.get("session_id") or "")
            session_ids.add(session_id)
            if latest_timestamp is None or timestamp > latest_timestamp:
                latest_timestamp = timestamp
                latest_session = session_id
    return latest_timestamp, latest_session, session_ids, unparseable_timestamps, diagnostics


def _load_session_events(path: Path, session_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and str(obj.get("session_id") or "") == session_id:
                events.append(obj)
    return events


def _read_ledger(path: Path) -> tuple[list[dict[str, Any]], bool, list[str]]:
    """Return only the latest session's events, bounded by that session's size."""
    try:
        latest_timestamp, latest_session, session_ids, unparseable_timestamps, diagnostics = _scan_ledger(path)
    except FileNotFoundError:
        return [], False, []
    except OSError:
        return [], True, []

    if len(session_ids) > 1:
        diagnostics.append(f"multiple sessions in ledger: {len(session_ids)}; using latest")
    if latest_timestamp is None:
        if unparseable_timestamps:
            diagnostics.append(f"skipped {unparseable_timestamps} event(s) with missing or unparseable timestamp")
        return [], False, diagnostics

    try:
        events = _load_session_events(path, latest_session)
    except OSError:
        return [], True, diagnostics
    return events, False, diagnostics


def _percentile(values: list[int], q: float) -> int:
    rank = max(1, math.ceil(q * len(values)))
    return _select_kth(values, rank - 1)


def _median(values: list[int]) -> int:
    midpoint = len(values) // 2
    if len(values) % 2:
        return _select_kth(values, midpoint)
    return int((_select_kth(values, midpoint - 1) + _select_kth(values, midpoint)) / 2)


def _select_kth(values: list[int], index: int) -> int:
    """Select an order statistic with deterministic worst-case linear work."""
    if not 0 <= index < len(values):
        raise IndexError("selection index out of range")
    if len(values) <= 5:
        return sorted(values)[index]
    groups = [values[offset : offset + 5] for offset in range(0, len(values), 5)]
    medians = [sorted(group)[len(group) // 2] for group in groups]
    pivot = _select_kth(medians, len(medians) // 2)
    lows = [value for value in values if value < pivot]
    pivots = [value for value in values if value == pivot]
    if index < len(lows):
        return _select_kth(lows, index)
    if index < len(lows) + len(pivots):
        return pivot
    highs = [value for value in values if value > pivot]
    return _select_kth(highs, index - len(lows) - len(pivots))


def _empty_report(
    repo: str, pr_number: str, artifact: Path, diagnostics: list[str], session_id: str = ""
) -> dict[str, Any]:
    return {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
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


def _merge_lifecycle(report: dict[str, Any], lifecycle: dict[str, Any]) -> None:
    for key in ("schema_version", "completeness", "items", "aggregates", "pr_durations_ms"):
        report[key] = lifecycle[key]
    diagnostics = report.setdefault("diagnostics", [])
    for diagnostic in lifecycle.get("diagnostics", []):
        if diagnostic not in diagnostics:
            diagnostics.append(diagnostic)


def _write_artifact(artifact: Path, report: dict[str, Any]) -> None:
    try:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(artifact, report)
    except OSError as exc:
        report["diagnostics"].append(f"cr-metrics artifact unavailable: {type(exc).__name__}")


def _emit_projection_event(report: dict[str, Any], *, started_at: float) -> None:
    aggregates = report.get("aggregates")
    aggregates = aggregates if isinstance(aggregates, dict) else {}
    eligible = int(aggregates.get("eligible_items") or 0)
    excluded = int(aggregates.get("excluded_items") or 0)
    total = eligible + excluded
    completeness = "empty" if total == 0 else ("complete" if excluded == 0 else "partial")
    eligible_bucket = "zero" if eligible == 0 else ("one" if eligible == 1 else ("small" if eligible <= 10 else "large"))
    reason_code = str(report.get("reason_code") or "")
    outcome = "ready" if reason_code == "CR_SUMMARY_READY" else ("empty" if reason_code == "CR_LEDGER_EMPTY" else "unavailable")
    try:
        from gh_address_cr.otel_tracing import add_current_span_event

        add_current_span_event(
            "cr_metrics.projection",
            {
                "gh_address_cr.cr_metrics.outcome": outcome,
                "gh_address_cr.cr_metrics.completeness": completeness,
                "gh_address_cr.cr_metrics.eligible_bucket": eligible_bucket,
                "gh_address_cr.cr_metrics.duration_ms": max(0.0, (time.monotonic() - started_at) * 1000),
            },
        )
    except Exception:
        return


def build_cr_summary(repo: str, pr_number: str, *, gate_completed_at: str | None = None) -> dict[str, Any]:
    started_at = time.monotonic()
    path = core_paths.evidence_ledger_file(repo, pr_number)
    artifact = core_paths.workspace_dir(repo, pr_number) / "cr-metrics.json"
    events, unreadable, diagnostics = _read_ledger(path)
    if unreadable:
        report: dict[str, Any] = {
            "schema_version": LIFECYCLE_SCHEMA_VERSION,
            "completeness": "unavailable",
            "status": "FAILED",
            "reason_code": "CR_SUMMARY_UNAVAILABLE",
            "repo": repo,
            "pr_number": str(pr_number),
            "diagnostics": ["evidence ledger unreadable"],
            "report_artifact": str(artifact),
        }
        _emit_projection_event(report, started_at=started_at)
        return report

    lifecycle = project_cr_lifecycle(
        events,
        repo=repo,
        pr_number=str(pr_number),
        gate_completed_at=gate_completed_at,
    )
    parsed = [(e, parse_iso_datetime(e.get("timestamp"))) for e in events]
    dropped_timestamp = sum(1 for _, t in parsed if t is None)
    if dropped_timestamp:
        diagnostics.append(f"skipped {dropped_timestamp} event(s) with missing or unparseable timestamp")
    valid = [(e, t) for e, t in parsed if t is not None]
    if not valid:
        report = _empty_report(repo, pr_number, artifact, diagnostics)
        _merge_lifecycle(report, lifecycle)
        _write_artifact(artifact, report)
        _emit_projection_event(report, started_at=started_at)
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
        _merge_lifecycle(report, lifecycle)
        _write_artifact(artifact, report)
        _emit_projection_event(report, started_at=started_at)
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

    span_ms: dict[str, Any]
    if completed_spans:
        span_ms = {
            "median": _median(completed_spans),
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
    _merge_lifecycle(report, lifecycle)
    _write_artifact(artifact, report)
    _emit_projection_event(report, started_at=started_at)
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
