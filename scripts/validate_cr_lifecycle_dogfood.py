#!/usr/bin/env python3
"""Run controlled pre-merge lifecycle sessions and emit a reproducible baseline."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from gh_address_cr import __version__
from gh_address_cr.commands.final_gate import write_native_final_gate_artifacts
from gh_address_cr.core.cr_metrics import LIFECYCLE_SCHEMA_VERSION, _distribution
from gh_address_cr.core.gate import COUNT_KEYS, GateResult
from gh_address_cr.core.session import SessionManager
from gh_address_cr.evidence.ledger import SessionEvidenceLedger

BASE_TIME = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_session(index: int) -> dict[str, Any]:
    repo = "dogfood/cr-lifecycle"
    pr_number = str(1000 + index)
    item_id = f"local:dogfood-{index:02d}"
    manager = SessionManager(repo, pr_number)
    session = manager.create(status="WAITING_FOR_GATE")
    session["items"] = {
        item_id: {
            "item_id": item_id,
            "item_kind": "local_finding",
            "source": "controlled_premerge",
            "state": "closed",
            "status": "CLOSED",
            "blocking": False,
            "handled": True,
            "validation_evidence": [{"command": "controlled lifecycle dogfood", "result": "passed"}],
        }
    }
    ledger = SessionEvidenceLedger(manager.ledger_path, session)
    observed_at = BASE_TIME + timedelta(minutes=index)
    addressed_at = observed_at + timedelta(seconds=2 + index)
    verified_at = addressed_at + timedelta(seconds=3 + (index % 3))
    for role, event_type, timestamp, payload in (
        ("intake", "finding_observed", observed_at, {"item_kind": "local_finding", "source": "controlled_premerge"}),
        ("fixer", "response_accepted", addressed_at, {"resolution": "fix"}),
        ("verifier", "response_accepted", verified_at, {"resolution": "accept"}),
    ):
        ledger.append_event(
            session_id=str(session["session_id"]),
            item_id=item_id,
            lease_id=None,
            agent_id=f"dogfood-{role}",
            role=role,
            event_type=event_type,
            payload=payload,
            timestamp=_timestamp(timestamp),
        )
    manager.save(session)
    result = GateResult(
        repo=repo,
        pr_number=pr_number,
        counts={key: 0 for key in COUNT_KEYS},
        failure_codes=[],
    )
    write_native_final_gate_artifacts(repo, pr_number, f"dogfood-{index:02d}", result)
    report = json.loads((manager.workspace_path / "cr-metrics.json").read_text(encoding="utf-8"))
    aggregates = report["aggregates"]
    return {
        "session_id": session["session_id"],
        "schema_version": report["schema_version"],
        "status": report["status"],
        "completeness": report["completeness"],
        "verified_items": aggregates["verified_items"],
        "eligible_items": aggregates["eligible_items"],
        "excluded_items": aggregates["excluded_items"],
        "observed_to_verified_ms": aggregates["observed_to_verified_ms"]["median"],
        "first_pass_numerator": aggregates["first_pass_verified_rate"]["numerator"],
        "first_pass_denominator": aggregates["first_pass_verified_rate"]["denominator"],
        "exclusion_reasons": sorted(
            reason for item in report["items"] for reason in item["exclusion_reasons"]
        ),
    }


def run_controlled_dogfood(*, session_count: int = 10) -> dict[str, Any]:
    if session_count < 10:
        raise ValueError("controlled dogfood requires at least 10 sessions")
    previous_state_dir = os.environ.get("GH_ADDRESS_CR_STATE_DIR")
    previous_disable_telemetry = os.environ.get("DISABLE_TELEMETRY")
    try:
        with tempfile.TemporaryDirectory(prefix="gh-address-cr-lifecycle-dogfood-") as tmp:
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = tmp
            os.environ["DISABLE_TELEMETRY"] = "1"
            sessions = [_run_session(index) for index in range(1, session_count + 1)]
    finally:
        if previous_state_dir is None:
            os.environ.pop("GH_ADDRESS_CR_STATE_DIR", None)
        else:
            os.environ["GH_ADDRESS_CR_STATE_DIR"] = previous_state_dir
        if previous_disable_telemetry is None:
            os.environ.pop("DISABLE_TELEMETRY", None)
        else:
            os.environ["DISABLE_TELEMETRY"] = previous_disable_telemetry

    durations = [int(session["observed_to_verified_ms"]) for session in sessions]
    eligible_items = sum(int(session["eligible_items"]) for session in sessions)
    excluded_items = sum(int(session["excluded_items"]) for session in sessions)
    first_pass_numerator = sum(int(session["first_pass_numerator"]) for session in sessions)
    first_pass_denominator = sum(int(session["first_pass_denominator"]) for session in sessions)
    return {
        "schema_version": "cr-lifecycle-dogfood.v1",
        "sample_kind": "controlled_premerge",
        "threshold_eligible": False,
        "runtime_version": __version__,
        "lifecycle_schema_version": LIFECYCLE_SCHEMA_VERSION,
        "session_count": len(sessions),
        "eligible_items": eligible_items,
        "excluded_items": excluded_items,
        "observed_to_verified_ms": _distribution(durations, total=eligible_items + excluded_items),
        "first_pass_verified_rate": {
            "numerator": first_pass_numerator,
            "denominator": first_pass_denominator,
            "rate": round(first_pass_numerator / first_pass_denominator, 4),
            "excluded": excluded_items,
        },
        "exclusion_reasons": sorted(
            reason for session in sessions for reason in session["exclusion_reasons"]
        ),
        "sessions": sessions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_controlled_dogfood(session_count=args.sessions)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
